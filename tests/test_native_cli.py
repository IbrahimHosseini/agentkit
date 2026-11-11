"""Offline lifecycle contracts, run on POSIX and native Windows with stdlib unittest."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def git_executable():
    # Avoid the macOS developer-tool shim creating caches inside test TMPDIR.
    direct = Path('/Applications/Xcode.app/Contents/Developer/usr/bin/git')
    return str(direct) if sys.platform == 'darwin' and direct.is_file() else shutil.which('git')


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class NativeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.git = git_executable()
        if not cls.git:
            raise RuntimeError('Git is required for the offline lifecycle tests')
        cls.fixture = tempfile.TemporaryDirectory(prefix='agentkit-fixture-')
        cls.source = Path(cls.fixture.name) / 'source'
        if os.environ.get('AGENTKIT_TEST_LEGACY') == '1':
            cls.source.mkdir()
            archive = subprocess.run([cls.git, '-C', str(ROOT), 'archive', 'HEAD'], check=True, stdout=subprocess.PIPE).stdout
            with tarfile.open(fileobj=io.BytesIO(archive)) as source_archive:
                source_archive.extractall(cls.source)
        else:
            shutil.copytree(ROOT, cls.source, ignore=shutil.ignore_patterns('.git', '__pycache__', '.DS_Store', 'tests'))
        cls.git_env = dict(os.environ, GIT_AUTHOR_NAME='test', GIT_COMMITTER_NAME='test',
                           GIT_AUTHOR_EMAIL='test@example.invalid', GIT_COMMITTER_EMAIL='test@example.invalid',
                           GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        for args in [('init', '-q'), ('symbolic-ref', 'HEAD', 'refs/heads/main'), ('add', '-A'), ('commit', '-qm', 'fixture')]:
            subprocess.run([cls.git, '-C', str(cls.source), *args], env=cls.git_env, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agentkit-native-')
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name) / 'space فارسی'
        self.home = self.scratch / 'home'
        self.home.mkdir(parents=True)
        self.repo = self.scratch / 'checkout'
        self.origin = self.scratch / 'origin.git'
        self.env = dict(self.git_env, HOME=str(self.home), USERPROFILE=str(self.home),
                        CODEX_HOME=str(self.home / 'codex custom'), CLAUDE_CONFIG_DIR=str(self.home / 'claude custom'),
                        AGENT_LOG_DIR=str(self.home / 'agent logs'), AGENTKIT_HOME=str(self.repo),
                        AGENTKIT_UPDATE_INTERVAL='0', NO_COLOR='1', PYTHONUTF8='1')
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'AGENTKIT_REQS_OK'):
            self.env.pop(key, None)
        self.git_run('clone', '-q', '--bare', str(self.source), str(self.origin))
        self.git_run('clone', '-q', str(self.origin), str(self.repo))
        self.stubs = self.scratch / 'fake CLIs'
        self.stubs.mkdir()
        self.env['PATH'] = str(self.stubs) + os.pathsep + self.env.get('PATH', '')
        for name in ('claude', 'codex', 'gh', 'bun'):
            stub = self.stubs / (name + '.cmd' if os.name == 'nt' else name)
            stub.write_text('@echo off\n@echo 1.0.0\n@exit /b 0\n' if os.name == 'nt' else '#!/bin/sh\nprintf "1.0.0\\n"\n', encoding='utf-8')
            stub.chmod(0o755)
        self.codex = Path(self.env['CODEX_HOME'])
        self.claude = Path(self.env['CLAUDE_CONFIG_DIR'])

    def git_run(self, *args, cwd=None, check=True):
        return subprocess.run([self.git, *args], cwd=cwd, env=self.env, check=check,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8')

    def cli(self, *args, expected=0):
        # Legacy mode is used only to capture a baseline during the migration.
        if os.environ.get('AGENTKIT_TEST_LEGACY') == '1' and os.name != 'nt':
            command = ['bash', str(self.repo / 'bin/agentkit'), *args]
        else:
            command = [sys.executable, '-I', str(self.repo / 'lib/agentkit.py'), *args]
        result = subprocess.run(command, cwd=self.scratch, env=self.env, input='',
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8')
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout)
        return result

    def install(self, target='codex', *args):
        return self.cli('install', '--target', target, '--yes', '--skip', 'gstack', '--skip', 'karpathy', *args)

    def publish_agent_change(self):
        publisher = self.scratch / 'publisher'
        self.git_run('clone', '-q', str(self.origin), str(publisher))
        agent = publisher / 'agents/backend.md'
        agent.write_bytes(agent.read_bytes() + b'\nOffline upstream update.\n')
        self.git_run('add', '-A', cwd=publisher)
        self.git_run('commit', '-qm', 'upstream change', cwd=publisher)
        self.git_run('push', '-q', 'origin', 'HEAD:main', cwd=publisher)

    def test_help_and_version(self):
        self.assertIn('install', self.cli('help').stdout)
        self.assertIn((self.repo / 'VERSION').read_text().strip(), self.cli('version').stdout)

    def test_dry_run_does_not_create_target_files(self):
        before = tree_bytes(self.home)
        self.install('both', '--dry-run')
        self.assertEqual(tree_bytes(self.home), before)
        self.assertFalse(self.codex.exists())
        self.assertFalse(self.claude.exists())

    def test_install_both_and_portable_manifest(self):
        self.install('both')
        self.assertTrue((self.codex / 'agents/backend.toml').is_file())
        self.assertTrue((self.claude / 'agents/backend.md').is_file())
        for target in (self.codex, self.claude):
            data = json.loads((target / 'agentkit/manifest.json').read_text(encoding='utf-8'))
            self.assertTrue(data['files'])
            for key, value in data['files'].items():
                self.assertNotIn('\\', key)
                self.assertFalse(key.startswith('/'))
                self.assertEqual(hashlib.sha256((target / key).read_bytes()).hexdigest(), value)
        self.cli('doctor', '--target', 'both')

    def test_doctor_reports_version_dirty_clone_and_path_without_failing(self):
        self.install()
        manifest = self.codex / 'agentkit/manifest.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['agentkit_version'] = '0.0.0-offline'
        manifest.write_text(json.dumps(data), encoding='utf-8')
        agent = self.repo / 'agents/backend.md'
        original = agent.read_bytes()
        agent.write_bytes(original + b'\nLocal worktree edit\n')
        warning = self.cli('doctor', '--target', 'codex').stdout
        self.assertIn('installed version 0.0.0-offline, repo version', warning)
        self.assertIn('AGENTKIT_HOME has local changes', warning)
        self.assertIn('$HOME/.local/bin is not on PATH', warning)
        self.assertNotIn('FAIL', warning)
        agent.write_bytes(original)
        data['agentkit_version'] = (self.repo / 'VERSION').read_text().strip()
        manifest.write_text(json.dumps(data), encoding='utf-8')
        local_bin = self.home / '.local/bin'
        local_bin.mkdir(parents=True)
        self.env['PATH'] = str(local_bin) + os.pathsep + self.env['PATH']
        healthy = self.cli('doctor', '--target', 'codex').stdout
        self.assertIn('AGENTKIT_HOME is clean', healthy)
        self.assertIn('$HOME/.local/bin is on PATH', healthy)
        self.assertIn('installed version ' + data['agentkit_version'], healthy)
        self.assertNotIn('FAIL', healthy)

    @unittest.skipIf(os.name == 'nt', 'POSIX optional integration boundary')
    def test_posix_doctor_warns_about_absent_optional_integrations(self):
        self.install('claude', '--skip', 'hooks')
        output = self.cli('doctor', '--target', 'claude').stdout
        for diagnostic in ('gstack not installed', 'karpathy plugin not installed',
                           'auto-update off', 'SubagentStop hook not in settings.json'):
            self.assertIn(diagnostic, output)
        self.assertNotIn('FAIL', output)

    @unittest.skipIf(os.name == 'nt', 'POSIX optional integration boundary')
    def test_posix_doctor_detects_fake_optional_integrations_without_installing(self):
        self.install('claude', '--skip', 'hooks')
        (self.claude / 'skills/gstack').mkdir()
        stub = self.stubs / 'claude'
        stub.write_text('#!/bin/sh\nif [ "$1 $2" = "plugin list" ]; then\n  printf "andrej-karpathy-skills\\n"\nelse\n  printf "1.0.0\\n"\nfi\n', encoding='utf-8')
        stub.chmod(0o755)
        hooks = {}
        for event, source in (('SessionStart', 'agentkit-auto-update'), ('SubagentStop', 'agentkit-agent-log')):
            hooks[event] = [{'_agentkit_source': source, 'hooks': [{'type': 'command', 'command': 'echo offline fixture', 'timeout': 5}]}]
        settings = self.claude / 'settings.json'
        settings.write_text(json.dumps({'hooks': hooks}), encoding='utf-8')
        before = settings.read_bytes()
        output = self.cli('doctor', '--target', 'claude').stdout
        for diagnostic in ('ok    gstack', 'ok    karpathy plugin', 'auto-update on', 'ok    SubagentStop hook in settings.json'):
            self.assertIn(diagnostic, output)
        self.assertNotIn('FAIL', output)
        self.assertEqual(settings.read_bytes(), before)

    @unittest.skipUnless(os.name == 'nt', 'requires actual native Windows')
    def test_windows_doctor_warns_unsupported_optional_integrations_without_failing(self):
        self.install('claude')
        output = self.cli('doctor', '--target', 'claude').stdout
        self.assertIn('Native Windows:', output)
        self.assertIn('gstack', output)
        self.assertIn('unavailable', output)
        self.assertNotIn('FAIL', output)

    def test_repeated_install_keeps_managed_bytes(self):
        self.install()
        before = {p.name: p.read_bytes() for p in (self.codex / 'agents').glob('*.toml')}
        self.install()
        self.assertEqual({p.name: p.read_bytes() for p in (self.codex / 'agents').glob('*.toml')}, before)
        self.assertEqual((self.codex / 'config.toml').read_text(encoding='utf-8').count('[agents.backend]'), 1)

    def test_foreign_agent_is_preserved_and_not_registered(self):
        foreign = self.codex / 'agents/backend.toml'
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(b'foreign backend\r\n')
        self.install()
        self.assertEqual(foreign.read_bytes(), b'foreign backend\r\n')
        self.assertNotIn('[agents.backend]', (self.codex / 'config.toml').read_text(encoding='utf-8'))
        self.cli('uninstall', '--target', 'codex', '--yes')
        self.assertEqual(foreign.read_bytes(), b'foreign backend\r\n')

    def test_edited_managed_file_survives_reinstall_and_uninstall(self):
        self.install()
        agent = self.codex / 'agents/backend.toml'
        edited = agent.read_bytes() + b'\n# user edit\n'
        agent.write_bytes(edited)
        self.install()
        self.assertEqual(agent.read_bytes(), edited)
        self.assertTrue(agent.with_name(agent.name + '.agentkit-new').is_file())
        self.cli('uninstall', '--target', 'codex', '--yes')
        self.assertEqual(agent.read_bytes(), edited)

    def test_force_replacement_backs_up_foreign_bytes(self):
        foreign = self.codex / 'agents/backend.toml'
        foreign.parent.mkdir(parents=True)
        original = b'foreign content\r\n'
        foreign.write_bytes(original)
        self.install('codex', '--force')
        self.assertNotEqual(foreign.read_bytes(), original)
        backups = list((self.codex / 'agentkit/backups').rglob('backend.toml'))
        self.assertTrue(any(p.read_bytes() == original for p in backups))

    def test_unmanaged_crlf_content_is_preserved(self):
        self.codex.mkdir(parents=True)
        original = b'# user config\r\nmodel = "user-model"\r\n'
        config = self.codex / 'config.toml'
        config.write_bytes(original)
        self.install()
        self.assertTrue(config.read_bytes().startswith(original), config.read_bytes())
        self.cli('uninstall', '--target', 'codex', '--yes')
        self.assertEqual(config.read_bytes(), original)

    def test_malformed_configuration_is_not_overwritten(self):
        self.codex.mkdir(parents=True)
        config = self.codex / 'config.toml'
        original = b'[broken\n'
        config.write_bytes(original)
        result = self.cli('install', '--target', 'codex', '--yes', '--skip', 'gstack', '--skip', 'karpathy', expected=None)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse((self.codex / 'agents/backend.toml').exists())

    def test_uninstall_dry_run_has_no_mutations(self):
        self.install()
        before = tree_bytes(self.home)
        self.cli('uninstall', '--target', 'codex', '--dry-run')
        self.assertEqual(tree_bytes(self.home), before)

    def test_purge_keeps_nondefault_checkout(self):
        self.install()
        self.cli('uninstall', '--target', 'codex', '--yes', '--purge')
        self.assertTrue((self.repo / '.git').is_dir())
        self.assertTrue((self.repo / 'VERSION').is_file())

    def test_project_purge_keeps_global_clone_launcher_and_target(self):
        default_clone = self.home / '.agentkit'
        shutil.move(str(self.repo), str(default_clone))
        self.repo = default_clone
        self.env['AGENTKIT_HOME'] = str(default_clone)
        self.install('claude')
        sentinel = self.claude / 'agents/user-owned.md'
        sentinel.write_bytes(b'global user agent\n')
        before_global = tree_bytes(self.claude)
        launcher_dir = self.home / '.local/bin'
        launcher_dir.mkdir(parents=True)
        if os.name == 'nt':
            launcher = launcher_dir / 'agentkit.cmd'
            launcher.write_bytes(b'global native launcher\r\n')
        else:
            launcher = launcher_dir / 'agentkit'
            launcher.symlink_to(default_clone / 'bin/agentkit')
        launcher_bytes = launcher.read_bytes()
        project = self.scratch / 'project'
        project.mkdir()
        self.cli('install', '--project', str(project), '--target', 'claude', '--yes', '--skip', 'gstack', '--skip', 'karpathy')
        self.assertTrue((project / '.claude/agents/backend.md').is_file())
        self.cli('uninstall', '--project', str(project), '--target', 'claude', '--yes', '--purge')
        self.assertTrue((default_clone / '.git').is_dir(), 'project purge removed global clone')
        self.assertTrue((default_clone / 'bin/agentkit').is_file())
        self.assertTrue(launcher.exists(), 'project purge removed global launcher')
        self.assertEqual(launcher.read_bytes(), launcher_bytes)
        self.assertEqual(tree_bytes(self.claude), before_global)
        self.assertEqual(sentinel.read_bytes(), b'global user agent\n')
        self.assertFalse((project / '.claude/agents/backend.md').exists())

    def test_update_fast_forwards_and_refreshes_managed_agent(self):
        self.install('claude')
        before = (self.claude / 'agents/backend.md').read_bytes()
        self.publish_agent_change()
        self.cli('update', '--target', 'claude')
        self.assertNotEqual((self.claude / 'agents/backend.md').read_bytes(), before)
        self.assertIn(b'Offline upstream update.', (self.claude / 'agents/backend.md').read_bytes())

    def test_update_rejects_dirty_checkout_without_changing_managed_files(self):
        self.install()
        before = tree_bytes(self.codex)
        source = self.repo / 'agents/backend.md'
        source.write_bytes(source.read_bytes() + b'\nUncommitted edit\n')
        result = self.cli('update', '--target', 'codex', expected=None)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(tree_bytes(self.codex), before)

    def test_update_rejects_divergent_checkout(self):
        self.install()
        before = tree_bytes(self.codex)
        local = self.repo / 'local.txt'
        local.write_text('local commit', encoding='utf-8')
        self.git_run('add', 'local.txt', cwd=self.repo)
        self.git_run('commit', '-qm', 'local divergence', cwd=self.repo)
        self.publish_agent_change()
        result = self.cli('update', '--target', 'codex', expected=None)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(tree_bytes(self.codex), before)

    def test_instruction_workflow_preserves_unicode_crlf_user_content(self):
        for target, name in ((self.claude, 'CLAUDE.md'), (self.codex, 'AGENTS.md')):
            target.mkdir(parents=True)
            (target / name).write_bytes('یادداشت کاربر\r\n'.encode('utf-8'))
        self.install('both')
        for target, name in ((self.claude, 'CLAUDE.md'), (self.codex, 'AGENTS.md')):
            self.assertTrue((target / name).read_bytes().startswith('یادداشت کاربر\r\n'.encode('utf-8')))
        self.cli('uninstall', '--target', 'both', '--yes')
        for target, name in ((self.claude, 'CLAUDE.md'), (self.codex, 'AGENTS.md')):
            self.assertEqual((target / name).read_bytes(), 'یادداشت کاربر\r\n'.encode('utf-8'))

    @unittest.skipIf(os.name == 'nt', 'symlink privileges are not required on Windows')
    def test_user_configuration_symlink_retains_identity(self):
        real = self.scratch / 'user config.toml'
        original = b'model = "user-model"\r\n'
        real.write_bytes(original)
        self.codex.mkdir(parents=True)
        config = self.codex / 'config.toml'
        config.symlink_to(real)
        self.install()
        self.assertTrue(config.is_symlink())
        self.assertTrue(real.read_bytes().startswith(original))
        self.cli('uninstall', '--target', 'codex', '--yes')
        self.assertTrue(config.is_symlink())
        self.assertEqual(real.read_bytes(), original)

    @unittest.skipIf(os.name == 'nt', 'symlink privileges are not required on Windows')
    def test_force_does_not_write_through_symlinked_agent_parent(self):
        outside = self.scratch / 'outside'
        outside.mkdir()
        original = b'user agent outside target\n'
        sentinel = outside / 'backend.toml'
        sentinel.write_bytes(original)
        self.codex.mkdir(parents=True)
        (self.codex / 'agents').symlink_to(outside, target_is_directory=True)
        self.cli('install', '--target', 'codex', '--yes', '--force', '--skip', 'gstack', '--skip', 'karpathy', expected=None)
        self.assertEqual(sentinel.read_bytes(), original)
        self.assertEqual(list(outside.iterdir()), [sentinel])

    @unittest.skipIf(os.name == 'nt', 'symlink privileges are not required on Windows')
    def test_force_replaces_leaf_agent_symlink_without_touching_outside_file(self):
        self.install()
        agent = self.codex / 'agents/backend.toml'
        expected = agent.read_bytes()
        outside = self.scratch / 'outside agent'
        original = b'user-owned outside agent\n'
        outside.write_bytes(original)
        agent.unlink()
        agent.symlink_to(outside)
        self.install('codex', '--force')
        self.assertEqual(outside.read_bytes(), original)
        self.assertFalse(agent.is_symlink())
        self.assertEqual(agent.read_bytes(), expected)
        backups = list((self.codex / 'agentkit/backups').rglob('backend.toml'))
        self.assertTrue(any(path.read_bytes() == original for path in backups), 'force replacement did not back up linked content')

    def test_uninstall_keeps_unrelated_empty_user_directories(self):
        self.install()
        empty = self.codex / 'user-data/keep-empty'
        empty.mkdir(parents=True)
        self.cli('uninstall', '--target', 'codex', '--yes')
        self.assertTrue(empty.is_dir(), 'uninstall deleted an unrelated empty user directory')
        self.assertEqual(list(empty.iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'symlink privileges are not required on Windows')
    def test_purge_does_not_remove_launcher_through_symlinked_parent(self):
        default_clone = self.home / '.agentkit'
        shutil.move(str(self.repo), str(default_clone))
        self.repo = default_clone
        self.env['AGENTKIT_HOME'] = str(default_clone)
        self.install()
        outside = self.scratch / 'outside launcher'
        outside.mkdir()
        user_file = outside / 'keep'
        user_file.write_bytes(b'outside user data')
        outside_launcher = outside / 'agentkit'
        outside_launcher.symlink_to(default_clone / 'bin/agentkit')
        link_target = os.readlink(outside_launcher)
        local = self.home / '.local'
        local.mkdir()
        (local / 'bin').symlink_to(outside, target_is_directory=True)
        self.cli('uninstall', '--target', 'codex', '--yes', '--purge')
        self.assertTrue(outside_launcher.is_symlink(), 'purge unlinked launcher through linked parent')
        self.assertEqual(os.readlink(outside_launcher), link_target)
        self.assertEqual(user_file.read_bytes(), b'outside user data')
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['agentkit', 'keep'])

    @unittest.skipIf(os.name == 'nt', 'symlink privileges are not required on Windows')
    def test_state_directory_symlink_does_not_write_outside_target(self):
        outside = self.scratch / 'outside state'
        outside.mkdir()
        (outside / 'keep').write_bytes(b'outside state')
        before = tree_bytes(outside)
        self.codex.mkdir(parents=True)
        (self.codex / 'agentkit').symlink_to(outside, target_is_directory=True)
        self.cli('install', '--target', 'codex', '--yes', '--skip', 'gstack', '--skip', 'karpathy', expected=None)
        self.assertEqual(tree_bytes(outside), before)

    @unittest.skipIf(os.name == 'nt', 'symlink privileges are not required on Windows')
    def test_backup_directory_symlink_does_not_write_outside_target(self):
        self.install()
        outside = self.scratch / 'outside backups'
        outside.mkdir()
        (outside / 'keep').write_bytes(b'outside backups')
        before = tree_bytes(outside)
        backups = self.codex / 'agentkit/backups'
        if backups.exists():
            shutil.rmtree(backups)
        backups.symlink_to(outside, target_is_directory=True)
        agent = self.codex / 'agents/backend.toml'
        agent.write_bytes(agent.read_bytes() + b'\n# edited\n')
        self.cli('install', '--target', 'codex', '--yes', '--force', '--skip', 'gstack', '--skip', 'karpathy', expected=None)
        self.assertEqual(tree_bytes(outside), before)

    @unittest.skipUnless(os.name == 'nt', 'requires actual native Windows')
    def test_windows_launcher_falls_back_from_invalid_python_and_propagates_errors(self):
        invalid = self.stubs / 'python.cmd'
        invalid.write_bytes(b'@echo off\r\n@exit /b 7\r\n')
        fallback = self.stubs / 'python3.cmd'
        fallback.write_text('@echo off\n@"' + sys.executable + '" %*\n@exit /b %errorlevel%\n', encoding='utf-8')
        launcher = self.repo / 'bin/agentkit.cmd'
        def invoke(*args):
            return subprocess.run([str(launcher), *args], cwd=self.scratch, env=self.env,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8')
        version = invoke('version')
        self.assertEqual(version.returncode, 0, version.stdout)
        self.assertIn((self.repo / 'VERSION').read_text().strip(), version.stdout)
        failure = invoke('help', '--definitely-invalid')
        self.assertNotEqual(failure.returncode, 0, failure.stdout)
        self.assertNotEqual(failure.returncode, 7, failure.stdout)

    @unittest.skipUnless(os.name == 'nt', 'requires actual native Windows')
    def test_windows_install_does_not_write_bash_hooks(self):
        result = self.cli('install', '--target', 'claude', '--yes')
        self.assertIn('Windows', result.stdout)
        settings = self.claude / 'settings.json'
        if settings.exists():
            data = json.loads(settings.read_text(encoding='utf-8'))
            self.assertFalse(data.get('hooks'), data)
        self.assertTrue((self.claude / 'agents/backend.md').is_file())

    @unittest.skipUnless(os.name == 'nt', 'requires actual native Windows')
    def test_windows_cmd_launcher_forwards_arguments(self):
        launcher = self.repo / 'bin/agentkit.cmd'
        result = subprocess.run([str(launcher), 'install', '--target', 'codex', '--yes', '--skip', 'gstack', '--skip', 'karpathy'],
                                cwd=self.scratch, env=self.env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((self.codex / 'agents/backend.toml').is_file())


if __name__ == '__main__':
    unittest.main()
