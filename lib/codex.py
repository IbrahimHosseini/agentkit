#!/usr/bin/env python3
"""Convert agentkit agents to Codex custom agents and manage the config.toml block.

Run with: python3 -I lib/codex.py <command> ...   (stdlib only, Python 3.9+)

  render-agent SRC.md MODELS_MAP KARPATHY_MD OUT.toml
  render-block SRC_AGENTS_DIR CODEX_AGENTS_DIR OUT_BLOCK
  config-put CONFIG BLOCK check|write   -> added | replaced | unchanged (exit 3: conflict)
  config-del CONFIG check|write         -> removed | none
  config-has CONFIG                     -> exit 0 if our block exists, else 1
"""
import json
import os
import re
import sys

START = '# agentkit:start'
END = '# agentkit:end'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
NAME_RE = re.compile(r'^[a-z0-9-]+$')
KARPATHY = ('andrej-karpathy-skills:karpathy-guidelines', 'karpathy-guidelines')


class Fail(Exception):
    def __init__(self, msg, code=2):
        Exception.__init__(self, msg)
        self.code = code


def rd(p):
    try:
        with open(p, encoding='utf-8', newline='') as f:
            return f.read()
    except FileNotFoundError:
        return None


def wr(p, s):
    p = os.path.realpath(p)  # never replace a symlink, write through it
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.agentkit-tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(s)
    if os.path.exists(p):
        os.chmod(tmp, os.stat(p).st_mode & 0o7777)
    os.replace(tmp, p)


def need(p):
    s = rd(p)
    if s is None:
        raise Fail('cannot read ' + p)
    return s


def q(s):
    # json string is a valid TOML basic string, except raw DEL
    return json.dumps(s, ensure_ascii=False).replace('\x7f', '\\u007f')


def parse_md(text, path):
    """Return (frontmatter dict, body). Lists become Python lists."""
    lines = text.replace('\r\n', '\n').split('\n')
    if not lines or lines[0].strip() != '---':
        raise Fail(path + ': missing frontmatter')
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == '---')
    except StopIteration:
        raise Fail(path + ': unterminated frontmatter')
    fm, key = {}, None
    for ln in lines[1:end]:
        m = re.match(r'^([A-Za-z_-]+):\s*(.*)$', ln)
        if m:
            key = m.group(1)
            fm[key] = m.group(2).strip() if m.group(2).strip() else []
        elif key and re.match(r'^\s+-\s+', ln) and isinstance(fm[key], list):
            fm[key].append(re.sub(r'^\s+-\s+', '', ln).strip())
    return fm, '\n'.join(lines[end + 1:]).strip('\n')


def agent_name(fm, path):
    name = fm.get('name') or os.path.basename(path)[:-3]
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise Fail('%s: invalid agent name %r (use [a-z0-9-]+)' % (path, name))
    return name


def load_map(path):
    m = {}
    for ln in need(path).splitlines():
        ln = ln.strip()
        if not ln or ln.startswith('#'):
            continue
        p = ln.split()
        if len(p) != 3:
            raise Fail('%s: bad line %r (want: alias model effort)' % (path, ln))
        m[p[0]] = (p[1], p[2])
    return m


def validate_toml(s, what):
    try:
        import tomllib
    except ImportError:  # Python < 3.11: minimal check, every line is a header, comment or key = "string"
        for i, ln in enumerate(s.splitlines(), 1):
            if not ln.strip() or ln.startswith('#') or re.match(r'^\[agents\.[a-z0-9-]+\]$', ln):
                continue
            m = re.match(r'^[a-z_]+ = ("(?:[^"\\]|\\.)*")$', ln)
            try:
                json.loads(m.group(1))
            except (AttributeError, ValueError):
                raise Fail('%s: generated invalid TOML at line %d' % (what, i), 4)
        return
    try:
        tomllib.loads(s)
    except Exception as e:  # tomllib.TOMLDecodeError
        raise Fail('%s: generated invalid TOML: %s' % (what, e), 4)


def render_agent(src, models, kmd, out):
    fm, body = parse_md(need(src), src)
    name = agent_name(fm, src)
    mp = load_map(models)
    alias = fm.get('model', '')
    if alias not in mp:
        raise Fail('%s: model %r not in %s' % (src, alias, models))
    model, effort = mp[alias]
    effort = fm.get('effort') or effort
    if effort not in EFFORTS:
        raise Fail('%s: effort %r not one of %s' % (src, effort, ', '.join(EFFORTS)))
    tools = [t.strip() for t in str(fm.get('tools', '')).split(',')]
    sandbox = 'workspace-write' if ('Edit' in tools or 'Write' in tools) else 'read-only'
    if name == 'security':
        sandbox = 'read-only'
    # Claude-only config folder -> Codex equivalent
    body = re.sub(r'(?:~|\$HOME)/\.claude/agents/\*\.md', '~/.codex/agents/*.toml', body)
    body = re.sub(r'(?:~|\$HOME)/\.claude/agents', '~/.codex/agents', body)
    skills = fm.get('skills') or []
    if any(s in KARPATHY for s in skills):
        body += '\n\n' + need(kmd).strip('\n')
    t = 'developer_instructions = %s\nmodel = %s\nmodel_reasoning_effort = %s\nsandbox_mode = %s\n' % (
        q(body + '\n'), q(model), q(effort), q(sandbox))
    validate_toml(t, src)
    wr(out, t)


def render_block(srcdir, cdir, out):
    items = []
    for fn in sorted(os.listdir(srcdir)):
        if not fn.endswith('.md'):
            continue
        p = os.path.join(srcdir, fn)
        fm, _ = parse_md(need(p), p)
        desc = fm.get('description')
        if not desc or not isinstance(desc, str):
            raise Fail(p + ': missing description')
        items.append((agent_name(fm, p), desc))
    if not items:
        raise Fail('no agents in ' + srcdir)
    names = [n for n, _ in items]
    if len(set(names)) != len(names):
        raise Fail('duplicate agent names in ' + srcdir)
    parts = [START, '# Managed by agentkit. Edits between the markers are overwritten.']
    for n, d in sorted(items):
        parts += ['[agents.%s]' % n, 'description = ' + q(d),
                  'config_file = ' + q(os.path.join(cdir, n + '.toml')), '']
    parts[-1] = END
    block = '\n'.join(parts) + '\n'
    validate_toml(block, 'block')
    wr(out, block)


def region(lines):
    """Return (start, end) line indexes of our block, or None. Raise on a broken pair."""
    s = [i for i, l in enumerate(lines) if l.strip() == START]
    e = [i for i, l in enumerate(lines) if l.strip() == END]
    if not s and not e:
        return None
    if len(s) != 1 or len(e) != 1 or e[0] < s[0]:
        raise Fail('unbalanced or duplicate agentkit markers in config')
    return s[0], e[0]


def block_names(block):
    return re.findall(r'^\[agents\.([a-z0-9-]+)\]\s*$', block, re.M)


def conflicts(outside, names):
    found = set()
    for l in outside:
        m = re.match(r'^\s*\[\s*agents\s*\.\s*(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_-]+))\s*[.\]]', l)
        if m:
            n = m.group(1) or m.group(2) or m.group(3)
            if n in names:
                found.add(n)
    return sorted(found)


def config_put(cfg, blockf, mode):
    block = need(blockf)
    text = rd(cfg) or ''
    try:
        import tomllib
    except ImportError:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('[') and not stripped.split('#', 1)[0].rstrip().endswith(']'):
                raise Fail('invalid TOML header in config')
    else:
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise Fail('invalid TOML config: ' + str(exc))
    lines = text.splitlines(keepends=True)
    r = region([l.rstrip('\r\n') for l in lines])
    outside = lines if r is None else lines[:r[0]] + lines[r[1] + 1:]
    bad = conflicts(outside, set(block_names(block)))
    if bad:
        raise Fail('agents already defined outside agentkit markers: ' + ' '.join(bad), 3)
    if r is None:
        head = ''.join(lines)
        if head and not head.endswith('\n'):
            head += '\n'
        new = head + ('\n' if head else '') + block
        res = 'added'
    else:
        new = ''.join(lines[:r[0]]) + block + ''.join(lines[r[1] + 1:])
        res = 'unchanged' if new == ''.join(lines) else 'replaced'
    if mode == 'write' and res != 'unchanged':
        wr(cfg, new)
    print(res)


def config_del(cfg, mode):
    text = rd(cfg)
    lines = (text or '').splitlines(keepends=True)
    r = region([l.rstrip('\r\n') for l in lines])
    if r is None:
        print('none')
        return
    s = r[0]
    if s > 0 and lines[s - 1].strip() == '':
        s -= 1  # the blank separator config-put added
    new = ''.join(lines[:s] + lines[r[1] + 1:])
    if mode == 'write':
        wr(cfg, new)
    print('removed')


def main(a):
    c = a[0] if a else ''
    n = {'render-agent': 4, 'render-block': 3, 'config-put': 3, 'config-del': 2, 'config-has': 1}
    if c not in n or len(a) - 1 != n[c]:
        raise Fail(__doc__)
    if c in ('config-put', 'config-del') and a[-1] not in ('check', 'write'):
        raise Fail('mode must be check or write')
    if c == 'render-agent':
        render_agent(*a[1:])
    elif c == 'render-block':
        render_block(*a[1:])
    elif c == 'config-put':
        config_put(*a[1:])
    elif c == 'config-del':
        config_del(*a[1:])
    else:
        sys.exit(0 if region((rd(a[1]) or '').splitlines()) else 1)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Fail as e:
        print('codex.py: ' + str(e), file=sys.stderr)
        sys.exit(e.code)
