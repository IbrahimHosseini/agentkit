"""Cross-platform agentkit lifecycle; no external Python dependencies."""
import argparse
import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

import codex
from . import integrations, platforms
from .managed import atomic_write, digest, linked_parent, load_manifest

ROOT = Path(__file__).resolve().parents[2]
START = '<!-- agentkit:start -->'
END = '<!-- agentkit:end -->'


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='agentkit', description='Commands: install update doctor uninstall version help; POSIX only: auto-update log feedback')
    p.add_argument('command', nargs='?', default='help')
    p.add_argument('--target', choices=['claude', 'codex', 'both'])
    p.add_argument('--project', type=Path)
    for flag in ['dry-run', 'force', 'quiet', 'purge']:
        p.add_argument('--' + flag, action='store_true')
    p.add_argument('--yes', '-y', action='store_true')
    p.add_argument('--skip', choices=['gstack', 'karpathy', 'claude-md', 'hooks', 'skills'], action='append', default=[])
    return p


class Lifecycle:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root = Path(os.environ.get('AGENTKIT_HOME', ROOT)).resolve()
        self.home = platforms.user_home()
        self.homes = {'claude': Path(os.environ.get('CLAUDE_CONFIG_DIR', self.home / '.claude')),
                      'codex': Path(os.environ.get('CODEX_HOME', self.home / '.codex'))}
        if args.project:
            if not args.project.is_dir():
                raise ValueError('project directory not found: ' + str(args.project))
            if args.target in ('codex', 'both'):
                raise ValueError('--project with codex is not supported')
            self.homes['claude'] = args.project.resolve() / '.claude'
        if not (self.root / 'VERSION').is_file():
            raise ValueError('AGENTKIT_HOME not found: ' + str(self.root))
        self.version = (self.root / 'VERSION').read_text().strip()
        self.stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.current = 'claude'
        for target_home in self.homes.values():
            for state_path in (target_home / 'agentkit', target_home / 'agentkit/backups'):
                if linked_parent(state_path, target_home):
                    raise ValueError('refusing linked state directory: ' + str(state_path))
        self.rows = []
        self.step = 0
        self.total_steps = 0

    def say(self, text: str) -> None:
        if not self.args.quiet:
            print(text, flush=True)

    def warn(self, text: str) -> None:
        print('warning: ' + text, file=sys.stderr)

    def ask(self, text: str) -> bool:
        if self.args.yes:
            return True
        self.say(text)
        if not sys.stdin.isatty():
            self.say('No TTY: not changing it. Use --yes to accept.')
            return False
        return input('[y/N] ').strip().lower() in ('y', 'yes')

    def targets(self) -> List[str]:
        if self.args.project:
            return ['claude']
        if self.args.target:
            return ['claude', 'codex'] if self.args.target == 'both' else [self.args.target]
        if self.args.command == 'install':
            found = [t for t in self.homes if platforms.find_command(t)]
        else:
            found = [t for t, home in self.homes.items() if (home / 'agentkit/manifest.json').exists()]
        return found or ['claude']

    @property
    def target(self) -> Path:
        return self.homes[self.current]

    def backup(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        try:
            rel = path.relative_to(self.target)
        except ValueError:
            rel = Path(path.name)
        dest = self.target / 'agentkit/backups' / self.stamp / rel
        if self.args.dry_run:
            self.say('[dry-run] back up ' + str(path))
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() and not path.exists():
            dest.symlink_to(os.readlink(path))
        elif path.is_symlink() and path.is_dir():
            dest.symlink_to(os.readlink(path), target_is_directory=True)
        elif path.is_dir():
            shutil.copytree(path, dest, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(path, dest)

    def helper(self, args: List[str]) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            integrations.main(args)
        return output.getvalue().strip()

    def requirements(self) -> None:
        if not platforms.is_windows():
            script = '. "$1"; YES="$2" DRY="$3" REQ_WANT="$4" check_requirements install'
            if os.environ.get('AGENTKIT_REQS_OK') == '1':
                return
            proc = platforms.run(['bash', '-c', script, '_', str(self.root / 'lib/requirements.sh'),
                                  str(int(self.args.yes)), str(int(self.args.dry_run)), self.args.target or 'auto'], stdout=subprocess.DEVNULL if self.args.quiet else None)
            if proc.returncode:
                raise ValueError('requirements are not met')
            return
        if sys.version_info < (3, 9):
            raise ValueError('Python >= 3.9 is required')
        missing = [name for name in ['git'] + self.targets() if not platforms.find_command(name)]
        if missing:
            raise ValueError('requirements are not met: install ' + ', '.join(missing) + ' and add them to PATH')

    def instruction_path(self) -> Path:
        if self.current == 'codex':
            return self.target / 'AGENTS.md'
        return (self.args.project / 'CLAUDE.md') if self.args.project else self.target / 'CLAUDE.md'

    def workflow(self, mode: str) -> None:
        if 'claude-md' in self.args.skip:
            return
        path = self.instruction_path()
        if mode != 'uninstall' and self.total_steps:
            self.step += 1
            self.say(f'[{self.step}/{self.total_steps}] ' + ('Codex: ' if self.current == 'codex' else 'Claude: ') + path.name)
        snip = self.root / 'templates' / ('AGENTS.md.snippet' if self.current == 'codex' else 'CLAUDE.md.snippet')
        if mode == 'update' and START not in (path.read_text(encoding='utf-8') if path.exists() else ''):
            return
        args = ['block-del', str(path), 'check'] if mode == 'uninstall' else ['block-put', str(path), str(snip), 'check']
        status = self.helper(args)
        if status in ('none', 'unchanged'):
            if status == 'unchanged':
                self.say('  = ' + path.name + ': block already up to date')
                self.rows.append((self.current, path.name, 'unchanged'))
            return
        if mode == 'install' and '# Multi-agent workflow' in (integrations.rd(str(path)) or '').replace(START, '') and START not in (integrations.rd(str(path)) or ''):
            self.say("WARNING: " + str(path) + " already has a '# Multi-agent workflow' section outside the agentkit markers")
        if self.args.dry_run:
            self.say('[dry-run] ' + path.name + ': ' + status + ' agentkit block')
            return
        if mode == 'install' and not self.ask('Insert the agentkit workflow block into ' + str(path) + '?'):
            return
        self.backup(path)
        args[-1] = 'write'
        self.helper(args)
        self.say('  + ' + path.name + ': ' + ('removed agentkit block' if mode == 'uninstall' else status + ' block'))
        self.rows.append((self.current, path.name, status))

    def sources(self, temporary: Path, old: dict) -> tuple:
        # Validate managed-tree boundaries before preparation can back up or
        # replace a foreign skill directory. --force never follows a parent.
        for category in ('agents', 'skills'):
            if category == 'skills' and 'skills' in self.args.skip:
                continue
            directory = self.target / category
            if linked_parent(directory, self.target):
                raise ValueError('refusing linked parent directory: ' + str(directory))
        files = {}
        eligible = temporary / 'sources'
        rendered = temporary / 'rendered'
        eligible.mkdir()
        rendered.mkdir()
        for src in sorted((self.root / 'agents').glob('*.md')):
            rel = 'agents/' + src.stem + ('.toml' if self.current == 'codex' else '.md')
            out = src
            if self.current == 'codex':
                out = rendered / (src.stem + '.toml')
                try:
                    codex.render_agent(str(src), str(self.root / 'codex/models.map'),
                                       str(self.root / 'codex/karpathy-guidelines.md'), str(out))
                except codex.Fail as exc:
                    raise ValueError('cannot render Codex agent ' + src.stem + ': ' + str(exc))
                dest = self.target / rel
                if dest.exists() and rel not in old and not self.args.force and (dest.is_symlink() or digest(dest) != digest(out)):
                    self.warn('Codex agent(s) ' + src.stem + ' not installed: ' + str(dest) + ' exists and is not managed by agentkit. Use --force to back it up and replace it.')
                    continue
                shutil.copy2(src, eligible / src.name)
            files[rel] = out
        if 'skills' not in self.args.skip:
            for folder in sorted((self.root / 'skills').iterdir()):
                if not (folder / 'SKILL.md').is_file():
                    continue
                if self.current == 'codex' and folder.name not in ('agent-report', 'security-audit', 'write-swift'):
                    continue
                dest = self.target / 'skills' / folder.name
                if linked_parent(dest.parent, self.target):
                    raise ValueError('refusing linked parent directory: ' + str(dest.parent))
                if linked_parent(dest, self.target) and not dest.is_symlink():
                    raise ValueError('refusing reparse point skill directory: ' + str(dest))
                source_files = [f for f in folder.rglob('*') if f.is_file() and f.name != '.DS_Store' and f.suffix != '.pyc']
                managed = any(k.startswith('skills/' + folder.name + '/') for k in old)
                identical = not dest.is_symlink() and all((dest / f.relative_to(folder)).is_file() and digest(dest / f.relative_to(folder)) == digest(f) for f in source_files)
                if (dest.exists() or dest.is_symlink()) and not managed and not identical:
                    if not self.args.force:
                        self.warn('skills/' + folder.name + (' is a symlink; skipped' if dest.is_symlink() else ' exists and is not managed by agentkit; skipped'))
                        files.update({k: None for k in old if k.startswith('skills/' + folder.name + '/')})
                        continue
                    self.backup(dest)
                    if not self.args.dry_run:
                        if dest.is_symlink():
                            dest.unlink()
                        else:
                            shutil.rmtree(dest)
                for src in source_files:
                    files[src.relative_to(self.root).as_posix()] = src
        else:
            files.update({k: None for k in old if k.startswith('skills/')})
        block = None
        if self.current == 'codex' and list(eligible.glob('*.md')):
            block = temporary / 'block.toml'
            codex.render_block(str(eligible), str(self.target / 'agents'), str(block))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    codex.config_put(str(self.target / 'config.toml'), str(block), 'check')
            except codex.Fail as exc:
                if exc.code != 3:
                    if 'agentkit markers' in str(exc):
                        self.warn('cannot use ' + str(self.target / 'config.toml') + ': ' + str(exc))
                        self.say('config.toml: no agents registered')
                        return files, None
                    raise
                conflicts = str(exc).split('markers: ', 1)[-1].split()
                for name in conflicts:
                    files.pop('agents/' + name + '.toml', None)
                    (eligible / (name + '.md')).unlink(missing_ok=True)
                self.warn('config.toml already defines agent(s) outside the agentkit markers: ' + ' '.join(conflicts) + '. Those are skipped.')
                if list(eligible.glob('*.md')):
                    codex.render_block(str(eligible), str(self.target / 'agents'), str(block))
                else:
                    block = None
        return files, block

    def sync(self, mode: str) -> None:
        manifest = self.target / 'agentkit/manifest.json'
        old = load_manifest(manifest)
        new = {}
        added = updated = same = forced = removed = 0
        self.say('agentkit ' + self.version + ': installing into ' + str(self.target))
        with tempfile.TemporaryDirectory(prefix='agentkit-render-') as work:
            files, block = self.sources(Path(work), old)
            for rel, src in files.items():
                dest = self.target / rel
                if linked_parent(dest.parent, self.target):
                    raise ValueError('refusing linked parent directory: ' + str(dest.parent))
                previous = old.get(rel)
                if src is None:
                    new[rel] = previous
                    continue
                sha = digest(src)
                exists = dest.exists() or dest.is_symlink()
                replace_link = dest.is_symlink()
                current_hash = digest(dest) if dest.is_file() else None
                if linked_parent(dest, self.target) and not self.args.force:
                    self.warn(rel + ' is a symlink; skipped')
                    if previous:
                        new[rel] = previous
                    continue
                if not exists and previous and mode == 'update':
                    new[rel] = previous
                    self.say('kept removed: ' + rel)
                    continue
                if exists and (current_hash != sha or replace_link):
                    if previous and current_hash != previous and not self.args.force:
                        if not self.args.dry_run:
                            atomic_write(Path(str(dest) + '.agentkit-new'), src.read_bytes())
                        new[rel] = previous
                        self.say('  ! kept your edited ' + rel + '; new version in ' + rel + '.agentkit-new')
                        continue
                    if not previous and not self.args.force:
                        self.warn(rel + ' exists and is not managed by agentkit; skipped (use --force to replace, with backup)')
                        continue
                    self.backup(dest)
                label = ''
                if not exists:
                    added += 1
                elif current_hash == sha and not replace_link:
                    same += 1
                elif self.args.force and (replace_link or not previous or current_hash != previous):
                    forced += 1
                    label = ' (replaced)'
                else:
                    updated += 1
                    label = ' (updated)'
                if not exists or current_hash != sha or replace_link:
                    self.say('  + ' + rel + label)
                if not self.args.dry_run:
                    if dest.is_symlink():
                        dest.unlink()
                    if not exists or current_hash != sha or replace_link:
                        atomic_write(dest, src.read_bytes())
                else:
                    self.say('[dry-run] copy ' + rel)
                new[rel] = sha
            for rel, sha in old.items():
                if rel in files:
                    continue
                dest = self.target / rel
                if dest.is_file() and not linked_parent(dest, self.target) and digest(dest) == sha:
                    if not self.args.dry_run:
                        dest.unlink()
                    removed += 1
                    self.say('  + ' + rel + ' (removed upstream)')
                elif dest.exists():
                    self.say('kept ' + rel + ' (removed upstream, but you edited it)')
            self.say(('  + ' if added + updated + forced + removed else '  = ') + f'Files: {added} added, {updated} updated, {same} unchanged, {forced} replaced (--force), {removed} removed upstream')
            self.rows.append((self.current, 'files', f'{added} added, {updated} updated, {same} unchanged'))
            if not self.args.dry_run:
                atomic_write(manifest, (json.dumps({'agentkit_version': self.version, 'files': dict(sorted(new.items()))}, indent=2) + '\n').encode())
            if block:
                if self.total_steps:
                    self.step += 1
                    self.say(f'[{self.step}/{self.total_steps}] Codex: config.toml')
                cfg = self.target / 'config.toml'
                if mode != 'update' or codex.region((codex.rd(str(cfg)) or '').splitlines()):
                    status = io.StringIO()
                    with contextlib.redirect_stdout(status):
                        codex.config_put(str(cfg), str(block), 'check')
                    if status.getvalue().strip() == 'unchanged':
                        self.say('  = config.toml: block already up to date')
                        self.rows.append((self.current, 'config.toml', 'unchanged'))
                    if status.getvalue().strip() != 'unchanged':
                        if self.args.dry_run:
                            self.say('[dry-run] config.toml: ' + status.getvalue().strip() + ' agentkit block')
                        elif mode == 'update' or self.ask('Register the agentkit agents in ' + str(cfg) + '?'):
                            self.backup(cfg)
                            with contextlib.redirect_stdout(io.StringIO()):
                                codex.config_put(str(cfg), str(block), 'write')
                            self.rows.append((self.current, 'config.toml', status.getvalue().strip()))
                        else:
                            self.say('  ! config.toml: skipped')
                            self.rows.append((self.current, 'config.toml', 'skipped'))
                            self.warn('the agent files in ' + str(self.target / 'agents') + ' are not registered in config.toml; codex doctor will warn about them')
            self.workflow(mode)

    def uninstall(self) -> None:
        if not self.args.dry_run and not self.ask('Remove agentkit files, hooks and the instruction blocks (CLAUDE.md, AGENTS.md, config.toml) for: ' + ' '.join(self.targets()) + '?'):
            raise ValueError('aborted')
        for target in self.targets():
            self.current = target
            self.say('target ' + target + ': ' + str(self.target))
            manifest = self.target / 'agentkit/manifest.json'
            if not manifest.exists():
                raise ValueError('agentkit is not installed in ' + str(self.target))
            managed_files = load_manifest(manifest)
            cleanup_dirs = {self.target / 'agentkit'}
            for rel, sha in managed_files.items():
                directory = (self.target / rel).parent
                while directory != self.target:
                    cleanup_dirs.add(directory)
                    directory = directory.parent
                dest = self.target / rel
                if dest.is_file() and not linked_parent(dest, self.target) and digest(dest) == sha:
                    if not self.args.dry_run:
                        dest.unlink()
                    else:
                        self.say('[dry-run] remove ' + rel)
                else:
                    self.say('Kept because you edited them: ' + rel)
            if target == 'codex':
                cfg = self.target / 'config.toml'
                if cfg.exists() and not self.args.dry_run:
                    self.backup(cfg)
                    with contextlib.redirect_stdout(io.StringIO()):
                        codex.config_del(str(cfg), 'write')
                    if cfg.stat().st_size == 0:
                        cfg.unlink()
                    self.say('config.toml: removed agentkit block')
                elif cfg.exists():
                    self.say('[dry-run] config.toml: remove agentkit block')
            self.workflow('uninstall')
            if target == 'claude':
                self.posix_integration('uninstall')
            if not self.args.dry_run:
                manifest.unlink()
                for directory in sorted(cleanup_dirs, key=lambda p: len(p.parts), reverse=True):
                    if directory.is_dir() and not linked_parent(directory, self.target):
                        try:
                            directory.rmdir()
                        except OSError:
                            pass
                if self.args.purge and (self.target / 'agentkit').exists():
                    shutil.rmtree(self.target / 'agentkit')
        self.say('Not removed: gstack and the karpathy plugin.')
        if 'claude' in self.targets():
            self.say('  gstack:   delete ' + str(self.homes['claude'] / 'skills/gstack') + ' and the settings.json entries marked _gstack_source')
        if 'codex' in self.targets():
            self.say('  gstack (codex): delete ' + str(self.homes['codex'] / 'skills/gstack-*') + ' (and the clone in ~/gstack if you want)')
        if self.args.purge and not self.args.project:
            # Refuse checkout deletion; retained clone is harmless and protects arbitrary overrides.
            default = self.home.resolve() / '.agentkit'
            link = self.home / '.local/bin/agentkit'
            if self.root == default and (self.root / '.git').is_dir():
                if not self.args.dry_run:
                    linked_launcher_parent = linked_parent(link.parent, self.home)
                    if linked_launcher_parent:
                        self.warn('Kept launcher under linked directory: ' + str(link.parent))
                    if not linked_launcher_parent and link.is_symlink() and link.resolve().is_relative_to(self.root):
                        link.unlink()
                    if platforms.is_windows():
                        native_link = self.home / '.local/bin/agentkit.cmd'
                        if not linked_launcher_parent and native_link.is_file() and not native_link.is_symlink():
                            if native_link.read_bytes() == platforms.launcher_bytes(self.root / 'lib/agentkit.py'):
                                native_link.unlink()
                            else:
                                self.warn('Kept edited or foreign launcher: ' + str(native_link))
                    shutil.rmtree(self.root)
            else:
                self.say('Kept ' + str(self.root) + ' (not the default ~/.agentkit git clone). Delete it by hand if you want.')

    def doctor(self) -> int:
        fails = 0
        self.say('agentkit ' + self.version + ' doctor')
        if platforms.is_windows() and not platforms.find_command('git'):
            self.say('FAIL git not found; install Git and add it to PATH')
            fails += 1
        if not platforms.is_windows():
            script = '. "$1"; REQ_WANT="$2" check_requirements report'
            proc = platforms.run(['bash', '-c', script, '_', str(self.root / 'lib/requirements.sh'), self.args.target or 'auto'], stdout=subprocess.DEVNULL if self.args.quiet else None)
            if proc.returncode:
                self.say('FAIL requirements not met')
                fails += 1
        local_bin = self.home / '.local/bin'
        paths = [Path(value).absolute() for value in os.environ.get('PATH', '').split(os.pathsep) if value]
        if local_bin.absolute() in paths:
            self.say('  ok    $HOME/.local/bin is on PATH')
        else:
            self.say('  warn  $HOME/.local/bin is not on PATH')
        if (self.root / '.git').exists():
            result = platforms.run(['git', '-C', str(self.root), 'status', '--porcelain'], capture_output=True, text=True)
            if result.returncode or result.stdout.strip():
                self.say('  warn  AGENTKIT_HOME has local changes (update may fail)')
            else:
                self.say('  ok    AGENTKIT_HOME is clean')
        else:
            self.say('  warn  AGENTKIT_HOME is not a git clone (update will not work)')
        for target in self.targets():
            self.current = target
            self.say('target ' + target + ': ' + str(self.target))
            manifest = self.target / 'agentkit/manifest.json'
            if not manifest.is_file():
                self.say('FAIL not installed in ' + str(self.target))
                fails += 1
                continue
            installed_files = load_manifest(manifest)
            installed_version = json.loads(manifest.read_text(encoding='utf-8')).get('agentkit_version', '')
            if installed_version == self.version:
                self.say('  ok    installed version ' + installed_version)
            else:
                self.say('  warn  installed version ' + str(installed_version) + ', repo version ' + self.version + ' (run: agentkit update)')
            for rel, sha in installed_files.items():
                path = self.target / rel
                if not path.is_file():
                    self.say('FAIL agent ' + Path(rel).stem + ': missing')
                    fails += 1
                elif digest(path) != sha:
                    self.say('warn agent ' + Path(rel).stem + ': modified (kept on update)')
                elif rel.startswith('agents/'):
                    self.say('  ok    agent ' + Path(rel).stem)
            for source in sorted((self.root / 'agents').glob('*.md')):
                rel = 'agents/' + source.stem + ('.toml' if target == 'codex' else '.md')
                if rel not in installed_files:
                    if (self.target / rel).exists():
                        self.say('  warn  agent ' + source.stem + ': not managed by agentkit')
                    else:
                        self.say('  FAIL  agent ' + source.stem + ': missing')
                        fails += 1
            for folder in sorted((self.target / 'skills').glob('*')):
                if (folder / 'SKILL.md').exists():
                    self.say('  ok    skill ' + folder.name)
            if START in (integrations.rd(str(self.instruction_path())) or ''):
                self.say('  ok    ' + self.instruction_path().name + ' block')
            else:
                self.say('  warn  ' + self.instruction_path().name + ' block not present')
            if target == 'codex':
                if codex.region((codex.rd(str(self.target / 'config.toml')) or '').splitlines()):
                    self.say('  ok    config.toml agents block')
                else:
                    self.say('  warn  config.toml agents block not present')
            elif not platforms.is_windows():
                if 'agentkit-agent-log' in (integrations.rd(str(self.target / 'settings.json')) or ''):
                    self.say('  ok    SubagentStop hook in settings.json')
                else:
                    self.say('  warn  SubagentStop hook not in settings.json')
            self.posix_integration('doctor')
            if platforms.is_windows():
                self.say('  warn  Native Windows: gstack, karpathy plugin, Bash hooks and auto-update integrations are unavailable')
            if not platforms.find_command(target):
                self.say('FAIL ' + target + ' CLI not found')
                fails += 1
        self.say('all required checks passed' if not fails else str(fails) + ' required check(s) failed')
        return int(bool(fails))

    def posix_integration(self, stage: str) -> None:
        if platforms.is_windows():
            return
        if stage == 'install' and 'hooks' not in self.args.skip and self.total_steps:
            self.step += 1
            self.say(f'[{self.step}/{self.total_steps}] Claude: SubagentStop hook')
        diagnostics = (
            'if gs_present "$CUR" >/dev/null; then echo "  ok    gstack"; else echo "  warn  gstack not installed"; fi; '
            'if [ "$CUR" = claude ]; then '
            'if command -v claude >/dev/null 2>&1; then '
            'if claude plugin list 2>/dev/null | grep -q andrej-karpathy-skills; then '
            'echo "  ok    karpathy plugin"; else echo "  warn  karpathy plugin not installed"; fi; fi; '
            'if [ -f "$SETTINGS" ] && py hook-has "$SETTINGS" agentkit-auto-update 2>/dev/null; then '
            'echo "  ok    auto-update on"; else echo "  warn  auto-update off (agentkit auto-update on)"; fi; fi'
        )
        scripts = {
            'doctor': diagnostics,
            'install': 'step_hooks',
            'update': 'refresh_hooks',
            'uninstall': 'hook_remove agentkit-',
            'extras': 'TARGETS="$4"; step_gstack; if has_target claude; then step_karpathy; fi; ui_summary_print',
        }
        opts = ['--target', self.current]
        for skip in self.args.skip:
            opts += ['--skip', skip]
        for key in ('yes', 'dry_run', 'force', 'quiet'):
            if getattr(self.args, key):
                opts.append('--' + key.replace('_', '-'))
        if self.args.project:
            opts += ['--project', str(self.args.project)]
        script = ('export AGENTKIT_LIBRARY_ONLY=1; . "$1"; shift; '
                  'parse_args "$@"; ui_init; resolve_target; set_target "$TARGET_OPT"; ' + scripts[stage])
        if stage == 'extras':
            script = script.replace('TARGETS="$4"', 'TARGETS="' + ' '.join(self.targets()) + '"')
        if stage == 'install':
            settings = self.target / 'settings.json'
            existing = integrations.rd(str(settings)) or ''
            self.rows.append((self.current, 'SubagentStop hook', 'unchanged' if 'agentkit-agent-log' in existing else 'added'))
        result = platforms.run(['bash', '-c', script, '_', str(self.root / 'lib/legacy-cli.sh')] + opts, stdout=subprocess.DEVNULL if stage == 'doctor' and self.args.quiet else None)
        if result.returncode:
            raise ValueError('POSIX integration failed')

    def execute(self) -> int:
        cmd = self.args.command
        if cmd == 'version':
            print(self.version)
        elif cmd == 'help':
            self.say('agentkit install | update | doctor | uninstall | version | help')
            parser().print_help()
        elif cmd == 'install':
            self.say('agentkit ' + self.version)
            if sys.stdout.isatty() and 'NO_COLOR' not in os.environ and not self.args.quiet:
                print('\033[36m( o.o )\033[0m')
            self.requirements()
            if self.args.dry_run:
                self.say('(dry run: nothing is written)')
            self.total_steps = sum(1 + int('claude-md' not in self.args.skip) + int(target == 'codex' or 'hooks' not in self.args.skip) for target in self.targets())
            for target in self.targets():
                self.current = target
                if self.args.target and not platforms.find_command(target):
                    self.warn(target + ' CLI not found; installing for --target ' + self.args.target + ' anyway')
                self.step += 1
                self.say(f'[{self.step}/{self.total_steps}] ' + ('Claude' if target == 'claude' else 'Codex') + ': agents and skills')
                self.sync('install')
                if target == 'claude':
                    self.posix_integration('install')
            self.posix_integration('extras')
            self.say('TARGET  ITEM  STATUS')
            for row in self.rows:
                self.say('  '.join(row))
            self.say('Done. Run agentkit doctor to check the setup.')
        elif cmd == 'update':
            if not (self.root / '.git').exists():
                raise ValueError(str(self.root) + ' is not a git clone, cannot update')
            for target in self.targets():
                if not (self.homes[target] / 'agentkit/manifest.json').is_file():
                    raise ValueError('agentkit is not installed in ' + str(self.homes[target]))
            if not self.args.dry_run:
                proc = platforms.run(['git', '-C', str(self.root), 'status', '--porcelain'], capture_output=True, text=True, check=True)
                if proc.stdout.strip():
                    raise ValueError('local changes: update refused; inspect git status')
                try:
                    platforms.run(['git', '-C', str(self.root), 'pull', '--ff-only'], check=True)
                except subprocess.CalledProcessError:
                    if self.args.quiet:
                        for home in self.homes.values():
                            if (home / 'agentkit').is_dir():
                                atomic_write(home / 'agentkit/update-status', b'agentkit: auto-update failed, see update.log\n')
                    raise ValueError('git pull --ff-only failed. Fix it by hand: cd ' + str(self.root) + ' && git status')
            else:
                self.say('[dry-run] git pull --ff-only')
            self.version = (self.root / 'VERSION').read_text(encoding='utf-8').strip()
            for target in self.targets():
                self.current = target
                if not (self.target / 'agentkit/manifest.json').exists():
                    raise ValueError('agentkit is not installed in ' + str(self.target))
                self.say(target + ': ' + str(self.target))
                self.sync('update')
                if target == 'claude':
                    self.posix_integration('update')
        elif cmd == 'doctor':
            return self.doctor()
        elif cmd == 'uninstall':
            self.uninstall()
        else:
            raise ValueError(cmd + ' is unsupported on native Windows; use install/update/doctor/uninstall or WSL for POSIX integrations')
        if platforms.is_windows() and cmd in ('install', 'update'):
            self.say('Native Windows: gstack, karpathy plugin, Bash hooks and auto-update integrations are not installed.')
        return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('--version', '-v'):
        argv[0] = 'version'
    if argv and argv[0] in ('--help', '-h'):
        argv[0] = 'help'
    try:
        for i, arg in enumerate(argv):
            if arg == '--target' and i + 1 == len(argv):
                raise ValueError('--target needs claude, codex or both')
            value = argv[i + 1] if arg == '--target' and i + 1 < len(argv) else arg.split('=', 1)[1] if arg.startswith('--target=') else None
            if value is not None and value not in ('claude', 'codex', 'both'):
                raise ValueError("--target: unknown value '" + value + "' (claude|codex|both)")
        return Lifecycle(parser().parse_args(argv)).execute()
    except (ValueError, OSError, codex.Fail, subprocess.CalledProcessError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
