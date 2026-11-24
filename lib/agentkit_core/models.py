"""Per-agent model preferences and a bounded, inference-free model picker.

Catalog entries describe capabilities, never an entitlement to use a model.
Preferences contain no credentials and are scoped to the installation target.
"""
import copy
import hashlib
import json
import os
import queue
import re
import signal
import tempfile
import subprocess
import sys
import threading
import time
from pathlib import Path

import codex
from . import desktop, platforms, ui
from .managed import atomic_write, digest, linked_parent, load_manifest

PREFERENCES = 'agentkit/model-overrides.json'
# Live catalogs may advertise levels beyond the bundled source-file schema.
EFFORT = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
MODEL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+()\[\]-]{0,255}$')
# OpenAI models cannot run as a Claude Code subagent model. For the Claude target
# the agent stays a Claude agent (the host) and relays its work to `codex exec`.
OPENAI_MODEL = re.compile(r'^(gpt-|chatgpt-|codex-|o[0-9])', re.I)
HOST_MODEL = 'sonnet'
RELAY_START = '<!-- agentkit:codex:start model={model} effort={effort} sandbox={sandbox} tools={tools} -->'
# The relay adds one newline after its end marker. Preserve any body spacing after it.
RELAY_RE = re.compile(r'<!-- agentkit:codex:start model=(\S+) effort=(\S+) sandbox=(\S+) tools=(\S*) -->\n.*?<!-- agentkit:codex:end -->\n?', re.S)


# The reverse: a Codex agent set to a Claude model stays on its own Codex model
# (the host) and relays its work to `claude -p`. The host needs full access because
# the default Codex sandbox blocks the network and writes to ~/.claude.
CLAUDE_MODEL = re.compile(r'^(opus|sonnet|haiku|fable|claude-)', re.I)
CLAUDE_RELAY_RE = re.compile(r'<!-- agentkit:claude:start model=(\S+) effort=(\S+) host_model=(\S+) host_effort=(\S+) host_sandbox=(\S+) -->\n.*?<!-- agentkit:claude:end -->\n*', re.S)


def is_claude(model):
    return bool(CLAUDE_MODEL.match(model or ''))


def claude_relay_block(model, effort, host_model, host_effort, host_sandbox):
    write = host_sandbox != 'read-only'
    command = 'claude -p --model ' + model + (' --effort ' + effort if effort else '')
    command += ' --permission-mode ' + ('acceptEdits --allowedTools Bash' if write else 'plan')
    return '\n'.join([
        '<!-- agentkit:claude:start model=%s effort=%s host_model=%s host_effort=%s host_sandbox=%s -->'
        % (model, effort or 'inherit', host_model, host_effort or 'inherit', host_sandbox),
        'You are a relay. This agent runs on the Claude model ' + model
        + (' with effort ' + effort if effort else '') + ' through the Claude Code CLI.',
        'Do not do the work yourself. Do this instead:',
        '1. Write a prompt file in a temporary directory. It holds the worker instructions (everything after the end marker of this block) and then the assignment you received.',
        '2. Run: `' + command + ' < prompt-file`',
        '3. Return the final output of that run and the real output of its checks. Add nothing of your own.',
        'If `claude` is missing, not logged in, or exits with an error, stop. Report the exact error and that no work was done.',
        '<!-- agentkit:claude:end -->', ''])


def is_openai(model):
    return bool(OPENAI_MODEL.match(model or ''))


def relay_block(model, effort, sandbox, tools):
    command = 'codex exec --skip-git-repo-check -m ' + model + ' -s ' + sandbox
    if effort:
        command += ' -c model_reasoning_effort=\\"' + effort + '\\"'
    command += ' -'
    return '\n'.join([
        RELAY_START.format(model=model, effort=effort or 'inherit', sandbox=sandbox, tools=tools),
        'You are a relay. This agent runs on the OpenAI model ' + model
        + (' with effort ' + effort if effort else '') + ' through the Codex CLI.',
        'Do not do the work yourself. Do this instead:',
        '1. Write a prompt file in your scratchpad. It holds the worker instructions (everything after the end marker of this block) and then the assignment you received.',
        '2. Run: `' + command + ' < prompt-file`',
        '3. Return the final message of that run and the real output of its checks. Add nothing of your own.',
        'If `codex` is missing, not logged in, or exits with an error, stop. Report the exact error and that no work was done.',
        '<!-- agentkit:codex:end -->', ''])


def sandbox_for(fm):
    tools = [t.strip() for t in str(fm.get('tools', '')).split(',')]
    name = fm.get('name')
    if isinstance(name, str) and (name == 'security' or name.startswith('security-')):
        return 'read-only'
    return 'workspace-write' if ('Edit' in tools or 'Write' in tools) else 'read-only'


def validate_choice(value):
    if (not isinstance(value, dict) or set(value) != {'model', 'effort'}
            or not isinstance(value['model'], str) or not MODEL_ID.fullmatch(value['model'])
            or (value['effort'] is not None and (not isinstance(value['effort'], str) or not EFFORT.fullmatch(value['effort'])))):
        raise ValueError('invalid model preference (expected model ID and supported effort or null)')
    return value


def load_preferences(home):
    path = home / PREFERENCES
    if linked_parent(path, home):
        raise ValueError('refusing linked model preferences: ' + str(path))
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('agents'), dict):
        raise ValueError('invalid model preferences: ' + str(path))
    for name, choice in data['agents'].items():
        if not codex.NAME_RE.fullmatch(name):
            raise ValueError('invalid agent name in ' + str(path))
        validate_choice(choice)
    return data['agents']


def default_choice(root, source, target):
    fm, _ = codex.parse_md(source.read_text(encoding='utf-8'), str(source))
    if target == 'codex':
        model, effort = codex.load_map(str(root / 'codex/models.map'))[fm['model']]
        return {'model': model, 'effort': fm.get('effort') or effort}
    return {'model': fm['model'], 'effort': fm.get('effort') or None}


def read_choice(data, target):
    text = data.decode('utf-8')
    if target == 'claude':
        fm, body = codex.parse_md(text, 'installed agent')
        relay = RELAY_RE.search(body)
        if relay:
            effort = relay.group(2)
            return validate_choice({'model': relay.group(1), 'effort': None if effort == 'inherit' else effort})
        return validate_choice({'model': fm.get('model'), 'effort': fm.get('effort') or None})
    values = {}
    match = re.search(r'^developer_instructions = (.+)$', text, re.M)
    relay = CLAUDE_RELAY_RE.search(json.loads(match.group(1))) if match else None
    if relay:
        return validate_choice({'model': relay.group(1), 'effort': None if relay.group(2) == 'inherit' else relay.group(2)})
    # Generated agents use one JSON-compatible TOML string per field.
    for key, name in [('model', 'model'), ('model_reasoning_effort', 'effort')]:
        match = re.search(r'^' + key + r' = (.+)$', text, re.M)
        values[name] = json.loads(match.group(1)) if match else None
    return validate_choice(values)


def patch_agent(data, target, choice):
    """Change only model fields; keep instructions, permissions and other bytes."""
    validate_choice(choice)
    text = data.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines(keepends=True)
    if target == 'claude':
        if not lines or lines[0].strip() != '---':
            raise ValueError('agent is missing frontmatter')
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
        if end is None:
            raise ValueError('unterminated agent frontmatter')
        fm, _ = codex.parse_md(text, 'agent')
        relay = is_openai(choice['model'])
        fields = ['model: ' + (HOST_MODEL if relay else choice['model']) + newline]
        if choice['effort'] is not None and not relay:
            fields.append('effort: ' + choice['effort'] + newline)
        middle = [line for line in lines[1:end] if not re.match(r'^(model|effort):', line)]
        rest = ''.join(lines[end + 1:]).replace('\r\n', '\n')
        previous = RELAY_RE.search(rest)
        tools = [t.strip() for t in str(fm.get('tools', '')).split(',') if t.strip()]
        original = previous.group(4) if previous else ','.join(tools)
        if previous and not relay:
            # Leaving the relay: put back the tools the agent had before it.
            middle = [('tools: ' + original.replace(',', ', ') + newline) if line.startswith('tools:') and original else line
                      for line in middle]
        elif relay and tools and 'Bash' not in tools:
            # The relay needs a shell to call Codex.
            middle = [line.rstrip('\r\n') + ', Bash' + newline if line.startswith('tools:') else line for line in middle]
        if relay or previous:
            # Only touch the body when a relay block is added or removed.
            body = RELAY_RE.sub('', rest)
            if relay:
                body = relay_block(choice['model'], choice['effort'], sandbox_for(fm), original) + body
            rest = body.replace('\n', newline) if newline == '\r\n' else body
        else:
            rest = ''.join(lines[end + 1:])
        text = ''.join(lines[:1] + middle + fields + [lines[end]]) + rest
        codex.parse_md(text, 'rendered agent')
    else:
        def value(key):
            found = re.search(r'^' + key + r' = (.+)$', text, re.M)
            return json.loads(found.group(1)) if found else None
        instructions = value('developer_instructions')
        previous = CLAUDE_RELAY_RE.search(instructions or '')
        relay = is_claude(choice['model'])
        if previous:
            host = {'model': previous.group(3), 'effort': None if previous.group(4) == 'inherit' else previous.group(4),
                    'sandbox': previous.group(5)}
        else:
            host = {'model': value('model'), 'effort': value('model_reasoning_effort'), 'sandbox': value('sandbox_mode')}
        if instructions is not None and (relay or previous):
            instructions = CLAUDE_RELAY_RE.sub('', instructions)
            if relay:
                instructions = claude_relay_block(choice['model'], choice['effort'], host['model'], host['effort'], host['sandbox']) + instructions
        model, effort = (host['model'], host['effort']) if relay else (choice['model'], choice['effort'])
        fields = ['model = ' + codex.q(model) + newline]
        if effort is not None:
            fields.append('model_reasoning_effort = ' + codex.q(effort) + newline)
        sandbox = 'danger-full-access' if relay else host['sandbox']
        kept = []
        for line in lines:
            if re.match(r'^(model|model_reasoning_effort)\s*=', line):
                continue
            if instructions is not None and re.match(r'^developer_instructions\s*=', line):
                line = 'developer_instructions = ' + codex.q(instructions) + newline
            elif sandbox is not None and re.match(r'^sandbox_mode\s*=', line):
                line = 'sandbox_mode = ' + codex.q(sandbox) + newline
            kept.append(line)
        text = ''.join(fields + kept)
        codex.validate_toml(text, 'rendered agent')
    return text.encode('utf-8')


def fallback_catalog(root, target):
    if target == 'claude':
        # Conservative common levels. Unknown/manual IDs inherit CLI effort.
        return [{'model': name, 'name': name, 'efforts': ['low', 'medium', 'high'] if name != 'haiku' else [],
                 'default': 'high' if name == 'opus' else 'medium' if name == 'sonnet' else None,
                 'hidden': False, 'source': 'local fallback', 'status': 'unverified'}
                for name in ('opus', 'sonnet', 'haiku')]
    result = []
    for model, effort in codex.load_map(str(root / 'codex/models.map')).values():
        if not any(item['model'] == model for item in result):
            # The mapping is the only locally verified capability. Do not guess
            # which additional levels a model accepts when discovery failed.
            result.append({'model': model, 'name': model, 'efforts': [effort], 'default': effort,
                           'hidden': False, 'source': 'local fallback', 'status': 'unverified'})
    return result


def codex_catalog(timeout=10, include_hidden=False):
    """JSON-RPC over stdio; no session or turn is started and no tokens are read."""
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(platforms.command_args(['codex', 'app-server']),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding='utf-8', start_new_session=os.name != 'nt')
    messages = queue.Queue(maxsize=64)
    stopped = threading.Event()

    def receive():
        try:
            while not stopped.is_set():
                line = proc.stdout.readline(1024 * 1024 + 1)
                if not line:
                    raise ValueError('model service closed its output')
                if len(line) > 1024 * 1024:
                    raise ValueError('model service response is too large')
                item = json.loads(line)
                while not stopped.is_set():
                    try:
                        messages.put(item, timeout=0.05)
                        break
                    except queue.Full:
                        pass
        except (OSError, ValueError) as exc:
            try:
                messages.put(exc, timeout=0.05)
            except queue.Full:
                pass
        finally:
            proc.stdout.close()

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()

    def send(message):
        proc.stdin.write(json.dumps(message) + '\n')
        proc.stdin.flush()

    def request(identifier, method, params):
        send({'id': identifier, 'method': method, 'params': params})
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('model discovery timed out')
            try:
                response = messages.get(timeout=remaining)
            except queue.Empty:
                raise ValueError('model discovery timed out') from None
            if isinstance(response, Exception):
                raise ValueError('model service returned an invalid response') from response
            if not isinstance(response, dict):
                raise ValueError('invalid model service response')
            if response.get('id') != identifier:
                continue
            if 'error' in response:
                # Do not echo arbitrary provider output, which can contain secrets.
                raise ValueError('model service rejected the request; check CLI login/version')
            return response.get('result')

    try:
        request(1, 'initialize', {'clientInfo': {'name': 'agentkit', 'version': '1'}})
        send({'method': 'initialized'})
        entries, cursor, seen = [], None, set()
        while True:
            page = request(len(seen) + 2, 'model/list', {'cursor': cursor, 'limit': 100, 'includeHidden': include_hidden})
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise ValueError('invalid model catalog')
            for item in page['data']:
                if not isinstance(item, dict):
                    raise ValueError('invalid model catalog entry')
                if item.get('hidden') and not include_hidden:
                    continue
                model = item.get('model')
                raw = item.get('supportedReasoningEfforts', [])
                if not isinstance(raw, list):
                    raise ValueError('invalid model effort list')
                efforts = [entry.get('reasoningEffort') for entry in raw if isinstance(entry, dict)]
                if len(efforts) != len(raw) or any(not isinstance(e, str) or not EFFORT.fullmatch(e) for e in efforts):
                    raise ValueError('unsupported model effort list; upgrade agentkit')
                default = item.get('defaultReasoningEffort') if efforts else None
                validate_choice({'model': model, 'effort': default})
                if default is not None and default not in efforts:
                    raise ValueError('invalid default effort')
                if not any(entry['model'] == model for entry in entries):
                    entries.append({'model': model, 'name': item.get('displayName') if isinstance(item.get('displayName'), str) and item['displayName'] else model,
                                    'efforts': efforts, 'default': default, 'hidden': bool(item.get('hidden')),
                                    'source': 'Codex app-server', 'status': 'reported'})
            cursor = page.get('nextCursor')
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen or len(seen) >= 100:
                raise ValueError('invalid catalog pagination')
            seen.add(cursor)
        if not entries:
            raise ValueError('model catalog is empty')
        return entries
    finally:
        stopped.set()
        if os.name != 'nt':
            # The launcher can exit before a child closes the inherited pipe.
            # Terminate our process group even when the launcher already exited.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                # Sandboxed hosts can report EPERM for an already-exited group.
                # Always reap the launcher below, even when group signaling fails.
                if proc.poll() is None:
                    proc.terminate()
        elif proc.poll() is None:
            # The installed CLI may be a .cmd wrapper with a child process.
            try:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except (OSError, subprocess.SubprocessError):
                proc.kill()
        try:
            proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader.join(timeout=0.2)
        if os.name != 'nt':
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            reader.join(timeout=0.2)
        try:
            proc.stdin.close()
        except OSError:
            pass  # A failed server may already have closed its input pipe.
        # Closing a buffered pipe from another thread can block on readline's
        # lock. Never turn a bounded discovery into an unbounded cleanup wait.
        if not reader.is_alive():
            proc.stdout.close()



def stop_process(proc):
    """Terminate only the helper process tree started by this module."""
    if os.name != 'nt':
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            if proc.poll() is None:
                proc.kill()
    elif proc.poll() is None:
        try:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except (OSError, subprocess.SubprocessError):
            proc.kill()
    proc.wait(timeout=2)


def bounded_run(args, timeout, cwd=None, stage='initialization'):
    proc = subprocess.Popen(platforms.command_args(args), cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            start_new_session=os.name != 'nt')
    try:
        output, _ = proc.communicate(timeout=timeout)
        if proc.returncode:
            if stage == 'setup':
                raise ValueError('Claude SDK setup failed; check npm network/registry access and retry')
            raise ValueError('Claude SDK initialization failed; run claude /login and check CLI version')
        if len(output) > 1024 * 1024:
            raise ValueError('Claude SDK catalog response is too large')
        return output
    except subprocess.TimeoutExpired:
        remedy = 'check npm network/registry access and retry' if stage == 'setup' else 'check connection and CLI login'
        raise ValueError('Claude SDK ' + stage + ' timed out; ' + remedy) from None
    finally:
        stop_process(proc)
        proc.stdout.close()


def claude_catalog(root, home, timeout=10):
    if home is None:
        raise ValueError('Claude SDK setup skipped; run without --dry-run to enable live discovery')
    deadline = time.monotonic() + timeout
    node = platforms.find_command('node')
    if not node:
        raise ValueError('Node.js is missing; install Node.js to enable live Claude discovery')
    executable = platforms.find_command('claude')
    if not executable:
        raise ValueError('Claude Code CLI is missing; install it and run claude /login')
    runtime = home / 'agentkit/runtime/claude-catalog'
    if linked_parent(runtime, home):
        raise ValueError('Claude SDK runtime is linked; use an ordinary target directory')
    for child in ('npm-cache', 'node_modules', 'package.json', 'package-lock.json', '.installed-lock-sha256',
                  'node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs'):
        if linked_parent(runtime / child, home):
            raise ValueError('Claude SDK runtime contains linked files; use an ordinary runtime directory')
    source = root / 'lib/claude_catalog'
    manifests = ['package.json', 'package-lock.json']
    marker = runtime / '.installed-lock-sha256'
    lock_digest = hashlib.sha256((source / 'package-lock.json').read_bytes()).hexdigest().encode('ascii')
    ready = marker.is_file() and marker.read_bytes() == lock_digest and all((runtime / name).is_file() and (runtime / name).read_bytes() == (source / name).read_bytes()
                for name in manifests) and (runtime / 'node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs').is_file()
    if not ready:
        npm = platforms.find_command('npm')
        if not npm:
            raise ValueError('npm is missing; install npm to set up the pinned Claude SDK')
        runtime.mkdir(parents=True, exist_ok=True)
        marker.unlink(missing_ok=True)
        for name in manifests:
            atomic_write(runtime / name, (source / name).read_bytes())
        bounded_run([npm, 'ci', '--ignore-scripts', '--omit=optional', '--no-audit', '--no-fund',
                     '--cache', str(runtime / 'npm-cache')], max(0.01, deadline - time.monotonic()), runtime, stage='setup')
        atomic_write(marker, lock_digest)
    with tempfile.TemporaryDirectory(prefix='agentkit-claude-catalog-') as cwd:
        raw = json.loads(bounded_run([node, str(source / 'discover.mjs'), str(runtime), executable, cwd],
                                    max(0.01, deadline - time.monotonic())))
    if not isinstance(raw, list) or not raw:
        raise ValueError('Claude SDK returned an empty or invalid catalog; check CLI login/version')
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('Claude SDK returned an invalid model entry')
        model = item.get('value')
        efforts = item.get('supportedEffortLevels')
        if efforts is None:
            efforts = []
        if not isinstance(efforts, list):
            raise ValueError('Claude SDK returned invalid effort capabilities')
        validate_choice({'model': model, 'effort': None})
        for effort in efforts:
            validate_choice({'model': model, 'effort': effort})
        entries.append({'model': model, 'name': item.get('displayName') if isinstance(item.get('displayName'), str) and item['displayName'] else model,
                        'efforts': efforts, 'default': None, 'hidden': False,
                        'source': 'Claude Agent SDK', 'status': 'reported'})
    return entries


def openai_entries(root, say):
    """OpenAI models a Claude agent can use by relaying to Codex. Never fails the picker."""
    try:
        found = [dict(item, source='Codex CLI (relay)') for item in codex_catalog() if is_openai(item['model'])]
        if found:
            return found
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    say('OpenAI models for Claude agents come from the local mapping (unverified). Install Codex and run codex login.')
    return [dict(item, source='local fallback (relay)') for item in fallback_catalog(root, 'codex')]


def claude_entries(root, say):
    say('Claude models for Codex agents come from the local list (unverified). Use m to enter another ID.')
    return [dict(item, source='local fallback (relay)') for item in fallback_catalog(root, 'claude')]


def catalog(root, target, say, home=None, include_hidden=False):
    try:
        result = codex_catalog(include_hidden=include_hidden) if target == 'codex' else claude_catalog(root, home)
        say('Models reported by ' + target + ' (access is not guaranteed).')
        if target == 'codex':
            return result + claude_entries(root, say)
        return result + openai_entries(root, say)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # SDK stderr/provider output is deliberately never printed.
        reason = str(exc) if isinstance(exc, ValueError) else 'helper could not start; check installed CLI and runtime'
        say('Live model discovery unavailable: ' + reason + '.')
    say('Local fallback: known models; access unverified. Check CLI login, version and account availability.')
    return fallback_catalog(root, target) + (openai_entries(root, say) if target == 'claude' else claude_entries(root, say))


def describe(choice):
    return choice['model'] + ' / ' + (choice['effort'] or 'inherit from CLI')


def yes_no(prompt, read=input):
    while True:
        value = read(prompt).strip().lower()
        if value in ('', 'n', 'no'):
            return False
        if value in ('y', 'yes'):
            return True


def choose(current, default, entries, say, read=input, show_all=None, *, terminal=None):
    terminal = terminal or ui.Terminal()
    say('Current: ' + describe(current) + '; agentkit default: ' + describe(default))
    options = []
    for index, item in enumerate(entries, 1):
        name = str(item.get('name', item['model']))
        hidden = ' (hidden)' if item.get('hidden') else ''
        efforts = ', '.join(item['efforts']) or 'inherit from CLI'
        if terminal.rich:
            options.append((str(index), name + hidden, item['model'], efforts))
        else:
            say(f'  {index}. {name} [{item["model"]}]{hidden} — efforts: {efforts}')
    if terminal.rich:
        if options:
            terminal.table(('Key', 'Model', 'Model ID', 'Effort levels'), options, say)
        actions = [('a', 'Show all models (including hidden)')] if show_all else []
        actions.extend((('m', 'Enter a model ID manually'), ('r', 'Restore agentkit default'),
                        ('Enter', 'Keep current model')))
        terminal.table(('Key', 'Action'), actions, say)
    else:
        if show_all:
            say('  a. Show all models (including hidden)')
        say('  m. Enter a model ID manually\n  r. Restore agentkit default\n  Enter: keep current model')
    while True:
        answer = read('Model: ').strip().lower()
        if answer == 'a' and show_all:
            entries[:] = show_all()
            return choose(current, default, entries, say, read, terminal=terminal)
        if answer == 'r':
            return None
        if not answer:
            selected = current['model']
            break
        if answer == 'm':
            selected = read('Model ID: ').strip()
            if MODEL_ID.fullmatch(selected):
                break
        elif answer.isdecimal() and 1 <= int(answer) <= len(entries):
            selected = entries[int(answer) - 1]['model']
            break
        say('Invalid model selection. Choose a listed number, m, r, or Enter.')
    info = next((item for item in entries if item['model'] == selected), None)
    if info is None:
        if selected == current['model']:
            say('Capabilities unknown; keeping the current effort. A different manual model inherits CLI effort.')
            return dict(current)
        say('Capabilities unknown; effort will inherit from the CLI.')
        return {'model': selected, 'effort': None}
    efforts = info['efforts']
    default_effort = (current['effort'] if current['effort'] in efforts
                      or (selected == current['model'] and current['effort'] is None) else info['default'])
    if not efforts:
        say('No configurable effort advertised; inherit from CLI.')
        return {'model': selected, 'effort': None}
    say('Effort (Enter: ' + (default_effort or 'inherit from CLI') + '):')
    if terminal.rich:
        options = [(str(index), effort) for index, effort in enumerate(efforts, 1)]
        terminal.table(('Key', 'Effort'), options + [('0', 'Inherit from CLI')], say)
    else:
        for index, effort in enumerate(efforts, 1):
            say(f'  {index}. {effort}')
        say('  0. Inherit from CLI')
    while True:
        answer = read('Effort: ').strip()
        if not answer:
            effort = default_effort
            break
        if answer.isdecimal() and 0 <= int(answer) <= len(efforts):
            effort = efforts[int(answer) - 1] if int(answer) else None
            break
        say('Invalid effort selection. Choose a listed number or Enter.')
    return {'model': selected, 'effort': effort}


def snapshot(path, home):
    if linked_parent(path, home):
        raise ValueError('refusing linked model configuration: ' + str(path))
    return path.read_bytes() if path.exists() else None


def gather(lifecycle, installing, targets=None, *, terminal=None):
    """Build a read-only inventory, excluding files the picker may not edit."""
    rows, states, skips = [], {}, []
    sources = sorted((lifecycle.root / 'agents').glob('*.md'))
    name_filter = getattr(lifecycle.args, 'agent', None)
    if name_filter and not any(src.stem == name_filter for src in sources):
        raise ValueError('unknown agent: ' + name_filter)
    for target in (targets if targets is not None else lifecycle.targets()):
        home = lifecycle.homes[target]
        roles = lifecycle.roles(target)
        if name_filter and name_filter not in roles.active:
            lifecycle.say(f'{target}/{name_filter}: agent excluded from this installation')
        for state_path in (home / 'agentkit', home / 'agentkit/backups'):
            if linked_parent(state_path, home):
                raise ValueError('refusing linked state directory: ' + str(state_path))
        manifest_path = home / 'agentkit/manifest.json'
        manifest_bytes = snapshot(manifest_path, home)
        if not installing and manifest_bytes is None:
            raise ValueError('agentkit is not installed in ' + str(home))
        files = load_manifest(manifest_path)
        preference_bytes = snapshot(home / PREFERENCES, home)
        preferences = load_preferences(home)
        states[target] = {'manifest': manifest_bytes, 'preferences': preference_bytes,
                          'agents': copy.deepcopy(preferences)}
        conflicts = []
        if target == 'codex':
            cfg_path = home / 'config.toml'
            cfg = cfg_path.read_bytes() if cfg_path.exists() else None
            lines = (cfg or b'').decode('utf-8').splitlines()
            try:
                region = codex.region(lines)
                outside = lines if region is None else lines[:region[0]] + lines[region[1] + 1:]
                conflicts = codex.conflicts(outside, {src.stem for src in sources})
            except codex.Fail:
                lifecycle.warn('model picker skipped Codex: invalid agentkit configuration markers')
                continue
        for src in sources:
            name = src.stem
            if name not in roles.active or (name_filter and name != name_filter):
                continue
            rel = 'agents/' + name + ('.toml' if target == 'codex' else '.md')
            dest = home / rel
            reason = None
            if name in conflicts:
                reason = 'agent is registered outside agentkit markers'
            elif linked_parent(dest, home):
                reason = 'linked file or directory'
            elif dest.exists() and (rel not in files or not dest.is_file() or digest(dest) != files[rel]):
                reason = 'unmanaged or manually edited file'
            elif not dest.exists() and (not installing or rel in files):
                reason = 'agent file is missing'
            if reason:
                if terminal and terminal.rich:
                    skips.append((target, name, reason))
                else:
                    lifecycle.say(f'{target}/{name}: model selection skipped ({reason})')
                continue
            default = default_choice(lifecycle.root, src, target)
            data = dest.read_bytes() if dest.exists() else None
            current = read_choice(data, target) if data is not None else preferences.get(name, default)
            rows.append({'target': target, 'name': name, 'rel': rel, 'source': src,
                         'before': data, 'current': current, 'default': default})
    if skips:
        lifecycle.say('Model selection skipped')
        terminal.table(('Target', 'Agent', 'Reason'), skips, lifecycle.say,
                       target_column=0, group_by=0)
    return rows, states


def show_table(rows, say, choices=None, *, terminal=None):
    terminal = terminal or ui.Terminal()
    display = []
    for row in rows:
        key = (row['target'], row['name'])
        choice = row['current'] if choices is None else choices.get(key, row['current'])
        if choice is None:
            choice = row['default']
        display.append((row['target'], row['name'], choice['model'], choice['effort'] or 'inherit from CLI'))
    terminal.table(('Target', 'Agent', 'Model', 'Effort'), display, say, target_column=0, group_by=0)


def configure(lifecycle, installing=False, read=None):
    """Collect the entire selection before any mutation. Return a commit batch."""
    read = read or input
    interactive = (not lifecycle.args.yes and sys.stdin.isatty()
                   and (not platforms.is_windows() or desktop.windows_console_input(sys.stdin)))
    # In quiet interactive mode the user must still see what the questions mean.
    say = print if interactive else lifecycle.say
    terminal = ui.Terminal(quiet=lifecycle.args.quiet)
    if not interactive:
        rows, _ = gather(lifecycle, installing, terminal=terminal)
        show_table(rows, say, terminal=terminal)
        say('Model settings kept. Run agentkit models in a terminal to change them.')
        return None
    try:
        targets = list(lifecycle.targets())
        if len(targets) > 1 and (installing or not lifecycle.args.target):
            if terminal.rich:
                say('Choose model settings target:')
                terminal.table(('Key', 'Target'), [('1', 'Claude'), ('2', 'Codex'), ('3', 'Both'),
                                                   ('0', 'Cancel')], say, target_column=1)
            else:
                say('Choose model settings target: 1. Claude  2. Codex  3. Both  0. Cancel')
            while True:
                answer = read('Target: ').strip().lower()
                if answer in ('0', 'c', 'cancel', ''):
                    say('Model changes cancelled.')
                    return None
                selected = {'1': ['claude'], '2': ['codex'], '3': targets,
                            'claude': ['claude'], 'codex': ['codex'], 'both': targets}.get(answer)
                if selected and all(target in targets for target in selected):
                    targets = selected
                    break
                say('Choose an installed target or cancel.')
        rows, states = gather(lifecycle, installing, targets, terminal=terminal)
        show_table(rows, say, terminal=terminal)
        if not rows:
            say('No eligible managed agents to configure.')
            return None
        if not yes_no('Do you want to change these models or effort levels? [y/N] ', read):
            return None
        choices, catalogs = {}, {}
        for row in rows:
            target = row['target']
            if target not in catalogs:
                catalogs[target] = catalog(lifecycle.root, target, say, home=None if lifecycle.args.dry_run else lifecycle.homes[target])
            say('\n' + terminal.target_label(target) + ' / ' + row['name'])
            show_all = (lambda: catalog(lifecycle.root, target, say, home=lifecycle.homes[target], include_hidden=True)) if target == 'codex' else None
            value = choose(row['current'], row['default'], catalogs[target], say, read, show_all, terminal=terminal)
            # An unchanged choice must not accidentally pin a source default.
            # An OpenAI model saved by an older agentkit has no relay block, so Claude Code
            # would load it as a Claude model ID and fail. Saving the same choice repairs it.
            broken = (target == 'claude' and row['before'] is not None and value is not None
                      and is_openai(value['model']) and b'agentkit:codex:start' not in row['before'])
            if value != row['current'] or broken or (value is None and row['name'] in states[target]['agents']):
                choices[(target, row['name'])] = value
        if not choices:
            say('No model changes selected.')
            return None
        say('\nProposed model settings:')
        show_table(rows, say, choices, terminal=terminal)
        if not yes_no('Apply changes? [y/N] ', read):
            say('Model changes cancelled.')
            return None
        return rows, states, choices
    except EOFError:
        say('\nModel changes cancelled (input ended).')
        return None
    # KeyboardInterrupt is intentionally propagated to stop the command before
    # installation continues. No choice has been written yet.


def preference_bytes(agents):
    return (json.dumps({'version': 1, 'agents': agents}, indent=2) + '\n').encode('utf-8')


def install_choices(lifecycle, batch, preferences):
    """Validate pending model choices and let the installer render them once."""
    rows, states, choices = batch
    target = lifecycle.current
    home = lifecycle.target
    for rel, state_key in [('agentkit/manifest.json', 'manifest'), (PREFERENCES, 'preferences')]:
        if snapshot(home / rel, home) != states[target][state_key]:
            raise ValueError('configuration changed while selecting models; rerun agentkit install')
    if target == 'codex':
        cfg = home / 'config.toml'
        lines = cfg.read_text(encoding='utf-8').splitlines() if cfg.exists() else []
        region = codex.region(lines)
        outside = lines if region is None else lines[:region[0]] + lines[region[1] + 1:]
        conflicts = codex.conflicts(outside, {name for chosen, name in choices if chosen == target})
        if conflicts:
            raise ValueError('agent registration changed while selecting models: ' + ', '.join(conflicts))
    for row in rows:
        key = (target, row['name'])
        if row['target'] != target or key not in choices:
            continue
        path = home / row['rel']
        if snapshot(path, home) != row['before']:
            raise ValueError('agent changed while selecting models: ' + str(path))
        if choices[key] is None:
            preferences.pop(key[1], None)
        else:
            preferences[key[1]] = validate_choice(choices[key])
    return preferences


def commit(lifecycle, batch):
    """Commit agents + preferences + manifests together, rolling back on error."""
    if batch is None:
        return
    import tempfile
    rows, states, choices = batch
    writes, originals, homes = {}, {}, {}
    changed_targets = {target for target, _ in choices}
    for target in changed_targets:
        home = lifecycle.homes[target]
        for rel, state_key in [('agentkit/manifest.json', 'manifest'), (PREFERENCES, 'preferences')]:
            path = home / rel
            if snapshot(path, home) != states[target][state_key]:
                raise ValueError('configuration changed while selecting models; rerun agentkit models')
            originals[path] = states[target][state_key]
            homes[path] = (target, home)
    manifests = {target: json.loads(states[target]['manifest']) if states[target]['manifest'] is not None
                 else {'agentkit_version': lifecycle.version, 'files': {}} for target in changed_targets}
    preferences = {target: copy.deepcopy(states[target]['agents']) for target in changed_targets}
    with tempfile.TemporaryDirectory(prefix='agentkit-models-') as work:
        for row in rows:
            target, name = row['target'], row['name']
            if (target, name) not in choices:
                continue
            home = lifecycle.homes[target]
            path = home / row['rel']
            if snapshot(path, home) != row['before']:
                raise ValueError('agent changed while selecting models: ' + str(path))
            # Recheck registration, too, before writing any selected file.
            if target == 'codex':
                cfg_path = home / 'config.toml'
                config_lines = cfg_path.read_text(encoding='utf-8').splitlines() if cfg_path.exists() else []
                region = codex.region(config_lines)
                outside = config_lines if region is None else config_lines[:region[0]] + config_lines[region[1] + 1:]
                if codex.conflicts(outside, {name}):
                    raise ValueError('agent registration changed while selecting models: ' + name)
            value = choices[(target, name)]
            if value is None:
                preferences[target].pop(name, None)
            else:
                preferences[target][name] = validate_choice(value)
            effective = value or row['default']
            data = row['before']
            if data is None:
                if target == 'claude':
                    data = row['source'].read_bytes()
                else:
                    rendered = Path(work) / (name + '.toml')
                    codex.render_agent(str(row['source']), str(lifecycle.root / 'codex/models.map'),
                                       str(lifecycle.root / 'codex/karpathy-guidelines.md'), str(rendered))
                    data = rendered.read_bytes()
            output = patch_agent(data, target, effective)
            writes[path] = output
            originals[path] = row['before']
            homes[path] = (target, home)
            manifests[target]['files'][row['rel']] = hashlib.sha256(output).hexdigest()
    for target in sorted(changed_targets):
        home = lifecycle.homes[target]
        writes[home / PREFERENCES] = preference_bytes(preferences[target])
        writes[home / 'agentkit/manifest.json'] = (json.dumps(manifests[target], indent=2) + '\n').encode('utf-8')
    if lifecycle.args.dry_run:
        for path in writes:
            lifecycle.say('[dry-run] update model settings: ' + str(path))
        return
    # Back up every original before the first replacement. Check again after
    # preparation; a concurrent external edit must never be silently adopted.
    for path in writes:
        target, home = homes[path]
        if snapshot(path, home) != originals[path]:
            raise ValueError('configuration changed before saving: ' + str(path))
        lifecycle.current = target
        lifecycle.backup(path)
    written = []
    try:
        for path, data in writes.items():
            written.append(path)  # include a write that fails after replacement
            atomic_write(path, data)
    except (Exception, KeyboardInterrupt):
        failures = []
        for path in reversed(written):
            try:
                if originals[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, originals[path])
            except OSError:
                failures.append(str(path))
        if failures:
            raise ValueError('model save failed; automatic recovery incomplete for ' + ', '.join(failures)
                             + '; restore originals from agentkit/backups/' + lifecycle.stamp) from None
        raise
    lifecycle.say('Model settings saved. Start a new target CLI session to load the updated agents.')
