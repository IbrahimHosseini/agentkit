"""Model selection contracts: temporary homes, offline catalogs and fake CLIs."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import codex
from agentkit_core import models
from agentkit_core.cli import Lifecycle, parser


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agentkit-model-tests-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                                   CODEX_HOME=str(self.home / '.codex'),
                                   CLAUDE_CONFIG_DIR=str(self.home / '.claude'), AGENTKIT_HOME=str(ROOT))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.output = io.StringIO()
        self.stdout = mock.patch('sys.stdout', self.output)
        self.stdout.start()
        self.addCleanup(self.stdout.stop)
        self.discovery = mock.patch('agentkit_core.desktop.discover', return_value={})
        self.discovery.start()
        self.addCleanup(self.discovery.stop)

    def lifecycle(self, *args):
        return Lifecycle(parser().parse_args(list(args)))

    def seed(self, target='claude', name='backend', life=None):
        life = life or self.lifecycle('models', '--target', target)
        home = life.homes[target]
        dest = home / 'agents' / (name + ('.toml' if target == 'codex' else '.md'))
        dest.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / 'agents' / (name + '.md')
        if target == 'codex':
            codex.render_agent(str(source), str(ROOT / 'codex/models.map'),
                               str(ROOT / 'codex/karpathy-guidelines.md'), str(dest))
        else:
            dest.write_bytes(source.read_bytes())
        manifest = home / 'agentkit/manifest.json'
        manifest.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(manifest.read_bytes()) if manifest.exists() else {'agentkit_version': 'test', 'files': {}, 'extra': 'keep'}
        payload['files'][dest.relative_to(home).as_posix()] = models.digest(dest)
        manifest.write_text(json.dumps(payload), encoding='utf-8')
        return life, dest

    def batch(self, life, answers, installing=False):
        with mock.patch('sys.stdin.isatty', return_value=True), mock.patch.object(models, 'catalog',
                side_effect=lambda root, target, say: models.fallback_catalog(root, target)):
            return models.configure(life, installing, read=mock.Mock(side_effect=answers))

    def test_numbered_selection_retry_and_effort(self):
        current = {'model': 'sonnet', 'effort': None}
        result = models.choose(current, current, models.fallback_catalog(ROOT, 'claude'), print,
                               mock.Mock(side_effect=['99', 'oops', '1', '9', '2']))
        self.assertEqual(result, {'model': 'opus', 'effort': 'medium'})
        self.assertIn('Invalid model', self.output.getvalue())
        self.assertIn('Invalid effort', self.output.getvalue())

    def test_manual_id_unknown_effort_and_invalid_id(self):
        current = {'model': 'opus', 'effort': 'high'}
        result = models.choose(current, current, [], print,
                               mock.Mock(side_effect=['m', 'bad\nmodel', 'm', 'provider/custom-v2']))
        self.assertEqual(result, {'model': 'provider/custom-v2', 'effort': None})

    def test_enter_unknown_model_preserves_effort(self):
        current = {'model': 'custom', 'effort': 'high'}
        self.assertEqual(models.choose(current, current, [], print, lambda _: ''), current)

    def test_incompatible_effort_uses_model_default(self):
        choice = models.choose({'model': 'old', 'effort': 'max'}, {'model': 'old', 'effort': 'max'},
                               [{'model': 'new', 'efforts': ['low', 'medium'], 'default': 'medium'}],
                               print, mock.Mock(side_effect=['1', '']))
        self.assertEqual(choice['effort'], 'medium')

    def test_unsupported_effort_is_removed(self):
        current = {'model': 'opus', 'effort': 'high'}
        choice = models.choose(current, current, models.fallback_catalog(ROOT, 'claude'), print, lambda _: '3')
        self.assertEqual(choice, {'model': 'haiku', 'effort': None})

    def test_claude_patch_preserves_body_and_unrelated_fields(self):
        data = b'---\r\nname: test\r\nmodel: sonnet\r\neffort: high\r\ntools: Read\r\n---\r\nBody\r\nmodel: leave me\r\n'
        patched = models.patch_agent(data, 'claude', {'model': 'opus', 'effort': None})
        self.assertTrue(patched.endswith(b'---\r\nBody\r\nmodel: leave me\r\n'))
        self.assertIn(b'tools: Read\r\n', patched)
        self.assertNotIn(b'effort:', patched)
        self.assertEqual(models.read_choice(patched, 'claude')['model'], 'opus')

    def test_codex_patch_preserves_instructions_and_sandbox(self):
        data = b'developer_instructions = "Use model = x\\n"\nmodel = "old"\nmodel_reasoning_effort = "high"\nsandbox_mode = "read-only"\n'
        patched = models.patch_agent(data, 'codex', {'model': 'new', 'effort': None})
        self.assertIn(b'developer_instructions = "Use model = x\\n"\n', patched)
        self.assertIn(b'sandbox_mode = "read-only"\n', patched)
        self.assertNotIn(b'model_reasoning_effort', patched)

    def test_command_changes_only_selected_agent_and_state(self):
        life, dest = self.seed()
        _, other = self.seed(name='docs')
        unrelated = life.homes['claude'] / 'skills/extra.txt'
        unrelated.parent.mkdir()
        unrelated.write_text('leave me')
        before = tree(self.home)
        batch = self.batch(life, ['y', '1', '2', '', '', 'y'])
        # Both agents are visited. backend changes; docs remains inherited.
        models.commit(life, batch)
        self.assertEqual(models.read_choice(dest.read_bytes(), 'claude'), {'model': 'opus', 'effort': 'medium'})
        self.assertEqual(other.read_bytes(), before[str(other.relative_to(self.home))])
        self.assertEqual(unrelated.read_text(), 'leave me')
        prefs = models.load_preferences(life.homes['claude'])
        self.assertEqual(prefs['backend']['model'], 'opus')
        manifest = json.loads((life.homes['claude'] / 'agentkit/manifest.json').read_bytes())
        self.assertEqual(manifest['extra'], 'keep')
        self.assertEqual(manifest['files']['agents/backend.md'], models.digest(dest))

    def test_n_and_empty_preserve_files(self):
        life, _ = self.seed()
        before = tree(self.home)
        for answer in ('n', ''):
            self.assertIsNone(self.batch(life, [answer]))
        self.assertEqual(tree(self.home), before)

    def test_final_rejection_and_eof_preserve_files(self):
        life, _ = self.seed()
        before = tree(self.home)
        self.assertIsNone(self.batch(life, ['y', '1', '2', 'n']))
        self.assertIsNone(self.batch(life, ['y', EOFError()]))
        self.assertIsNone(self.batch(life, ['y', '1', '2', EOFError()]))
        self.assertEqual(tree(self.home), before)

    def test_interrupt_before_commit_preserves_files(self):
        life, _ = self.seed()
        before = tree(self.home)
        with self.assertRaises(KeyboardInterrupt):
            self.batch(life, ['y', KeyboardInterrupt()])
        self.assertEqual(tree(self.home), before)

    def test_noninteractive_and_yes_do_not_discover_or_prompt(self):
        life, _ = self.seed()
        before = tree(self.home)
        for args, tty in [(['models', '--target', 'claude'], False), (['install', '--target', 'claude', '--yes'], True)]:
            with mock.patch('sys.stdin.isatty', return_value=tty), mock.patch.object(models, 'catalog') as discover:
                read = mock.Mock(side_effect=AssertionError('unexpected prompt'))
                self.assertIsNone(models.configure(self.lifecycle(*args), args[0] == 'install', read))
                discover.assert_not_called()
        self.assertEqual(tree(self.home), before)

    def test_dry_run_does_not_save(self):
        life, _ = self.seed()
        life.args.dry_run = True
        before = tree(self.home)
        models.commit(life, self.batch(life, ['y', '1', '2', 'y']))
        self.assertEqual(tree(self.home), before)
        self.assertIn('[dry-run]', self.output.getvalue())

    def test_filter_unknown_and_missing_install(self):
        with self.assertRaisesRegex(ValueError, 'not installed'):
            models.gather(self.lifecycle('models', '--target', 'codex'), False)
        life, _ = self.seed()
        life.args.agent = 'missing'
        with self.assertRaisesRegex(ValueError, 'unknown agent'):
            models.gather(life, False)
        life.args.agent = 'backend'
        rows, _ = models.gather(life, False)
        self.assertEqual([row['name'] for row in rows], ['backend'])

    def test_skip_edited_foreign_missing_and_linked_files(self):
        life, dest = self.seed()
        dest.write_bytes(dest.read_bytes() + b'Edited\n')
        _, foreign = self.seed(name='docs')
        manifest = life.homes['claude'] / 'agentkit/manifest.json'
        data = json.loads(manifest.read_bytes())
        del data['files']['agents/docs.md']
        manifest.write_text(json.dumps(data))
        rows, _ = models.gather(life, False)
        self.assertEqual(rows, [])
        self.assertIn('unmanaged or manually edited', self.output.getvalue())
        try:
            foreign.unlink()
            foreign.symlink_to(dest)
        except OSError:
            return  # native Windows can lack symlink privileges
        rows, _ = models.gather(life, False)
        self.assertEqual(rows, [])
        self.assertIn('linked file', self.output.getvalue())

    def test_codex_foreign_registration_is_skipped(self):
        life, _ = self.seed('codex')
        (life.homes['codex'] / 'config.toml').write_text('[agents.backend]\nconfig_file = "mine.toml"\n')
        self.assertEqual(models.gather(life, False)[0], [])

    def test_both_targets_and_project(self):
        life = self.lifecycle('models', '--target', 'both', '--agent', 'backend')
        self.seed('claude', life=life)
        self.seed('codex', life=life)
        models.commit(life, self.batch(life, ['y', '1', '2', '1', '1', 'y']))
        for target in ('claude', 'codex'):
            self.assertIn('backend', models.load_preferences(life.homes[target]))
        project = self.home / 'project'
        project.mkdir()
        project_life = self.lifecycle('models', '--project', str(project), '--agent', 'backend')
        _, dest = self.seed(life=project_life)
        models.commit(project_life, self.batch(project_life, ['y', '1', '2', 'y']))
        self.assertTrue(dest.is_relative_to(project.resolve()))
        self.assertEqual(models.read_choice(dest.read_bytes(), 'claude')['model'], 'opus')

    def test_restore_removes_override(self):
        life, dest = self.seed()
        models.commit(life, self.batch(life, ['y', '1', '2', 'y']))
        models.commit(life, self.batch(life, ['y', 'r', 'y']))
        self.assertEqual(models.load_preferences(life.homes['claude']), {})
        self.assertEqual(models.read_choice(dest.read_bytes(), 'claude'), models.default_choice(ROOT, ROOT / 'agents/backend.md', 'claude'))

    def test_update_keeps_override_and_replaces_source_instructions(self):
        for target in ('claude', 'codex'):
            life, dest = self.seed(target)
            models.commit(life, self.batch(life, ['y', 'm', 'custom-model', 'y']))
            life.args.skip = ['skills', 'claude-md']
            life.args.yes = True
            life.current = target
            # sync is the shared installation/update renderer; use a new source
            # tree to demonstrate upstream body changes with the same preference.
            source = self.home / ('source-' + target)
            import shutil
            shutil.copytree(ROOT / 'agents', source / 'agents')
            shutil.copytree(ROOT / 'codex', source / 'codex')
            agent = source / 'agents/backend.md'
            agent.write_bytes(agent.read_bytes() + b'\nNew upstream instructions.\n')
            life.root = source
            life.sync('update')
            self.assertEqual(models.read_choice(dest.read_bytes(), target), {'model': 'custom-model', 'effort': None})
            self.assertIn(b'New upstream instructions.', dest.read_bytes())
            manifest = json.loads((life.homes[target] / 'agentkit/manifest.json').read_bytes())
            self.assertEqual(manifest['files'][dest.relative_to(life.homes[target]).as_posix()], models.digest(dest))

    def test_new_install_preferences_are_applied(self):
        life = self.lifecycle('install', '--target', 'claude')
        with mock.patch.object(life, 'targets', return_value=['claude']):
            rows, states = models.gather(life, True)
        row = next(row for row in rows if row['name'] == 'backend')
        models.commit(life, (rows, states, {('claude', 'backend'): {'model': 'opus', 'effort': 'high'}}))
        life.current = 'claude'
        life.args.skip = ['skills', 'claude-md']
        life.args.yes = True
        life.sync('install')
        dest = life.homes['claude'] / row['rel']
        self.assertEqual(models.read_choice(dest.read_bytes(), 'claude'), {'model': 'opus', 'effort': 'high'})

    def test_install_prompt_is_after_requirements_before_desktop(self):
        life = self.lifecycle('install', '--target', 'claude', '--yes', '--skip', 'skills', '--skip', 'claude-md')
        order = []
        with mock.patch.object(life, 'requirements', side_effect=lambda: order.append('requirements')), \
             mock.patch.object(models, 'configure', side_effect=lambda *a, **kw: order.append('models')), \
             mock.patch.object(life, 'desktop_installations', side_effect=lambda: order.append('desktop')), \
             mock.patch.object(life, 'sync'), mock.patch.object(life, 'posix_integration'):
            life.execute()
        self.assertEqual(order, ['requirements', 'models', 'desktop'])

    def test_save_failure_rolls_back_agents_manifest_preferences(self):
        life, dest = self.seed()
        batch = self.batch(life, ['y', '1', '2', 'y'])
        original = tree(self.home)
        real_write = models.atomic_write
        failed = False

        def fail_once(path, data):
            nonlocal failed
            if path.name == 'manifest.json' and not failed:
                failed = True
                raise OSError('simulated disk failure')
            return real_write(path, data)

        with mock.patch.object(models, 'atomic_write', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'simulated disk failure'):
                models.commit(life, batch)
        restored = {name: data for name, data in tree(self.home).items() if 'backups' not in Path(name).parts}
        self.assertEqual(restored, original)
        self.assertTrue(list((life.homes['claude'] / 'agentkit/backups').rglob('backend.md')))

    def test_failure_in_second_target_restores_both(self):
        life = self.lifecycle('models', '--target', 'both', '--agent', 'backend')
        self.seed('claude', life=life)
        self.seed('codex', life=life)
        batch = self.batch(life, ['y', '1', '2', '1', '1', 'y'])
        before = tree(self.home)
        real_write = models.atomic_write
        failed = False

        def fail_once(path, data):
            nonlocal failed
            if path == life.homes['codex'] / 'agentkit/manifest.json' and not failed:
                failed = True
                raise OSError('second target save failed')
            real_write(path, data)

        with mock.patch.object(models, 'atomic_write', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'second target'):
                models.commit(life, batch)
        self.assertEqual({name: data for name, data in tree(self.home).items() if 'backups' not in Path(name).parts}, before)

    def test_read_only_command_entrypoint(self):
        self.seed('codex')
        before = tree(self.home)
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'lib/agentkit.py'),
                                 'models', '--target', 'codex', '--agent', 'backend'],
                                input='', capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('backend', result.stdout)
        self.assertIn('Model settings kept', result.stdout)
        self.assertEqual(tree(self.home), before)

    def test_concurrent_edit_aborts_before_any_write(self):
        life, dest = self.seed()
        batch = self.batch(life, ['y', '1', '2', 'y'])
        dest.write_bytes(dest.read_bytes() + b'concurrent edit')
        before = tree(self.home)
        with self.assertRaisesRegex(ValueError, 'changed while selecting'):
            models.commit(life, batch)
        self.assertEqual(tree(self.home), before)

    def test_invalid_preferences_and_symlink_are_rejected(self):
        life, _ = self.seed()
        pref = life.homes['claude'] / models.PREFERENCES
        for value in [{'version': 2, 'agents': {}}, {'version': 1, 'agents': {'backend': {'model': 'bad\nmodel', 'effort': None}}}]:
            pref.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                models.load_preferences(life.homes['claude'])
        pref.unlink()
        try:
            pref.symlink_to(self.home / 'outside')
        except OSError:
            return
        with self.assertRaisesRegex(ValueError, 'linked'):
            models.load_preferences(life.homes['claude'])


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agentkit-catalog-tests-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        env = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                              CODEX_HOME=str(self.home / '.codex'), CLAUDE_CONFIG_DIR=str(self.home / '.claude'))
        env.start()
        self.addCleanup(env.stop)

    def fake(self, body):
        path = self.home / 'fake_server.py'
        path.write_text('import sys, json, time, os\n' + body, encoding='utf-8')
        return mock.patch.object(models.platforms, 'command_args', return_value=[sys.executable, '-I', str(path)])

    def test_live_pagination_efforts_and_no_inference(self):
        requests = self.home / 'requests.jsonl'
        code = '''
for line in sys.stdin:
    request = json.loads(line)
    with open(%r, 'a') as out:
        out.write(line)
    method = request['method']
    if method == 'initialized':
        continue
    if method == 'initialize':
        result = {}
    elif method == 'model/list':
        cursor = request['params']['cursor']
        result = {'data': [{'model': 'model-b' if cursor else 'model-a',
                           'supportedReasoningEfforts': [{'reasoningEffort': 'minimal'}, {'reasoningEffort': 'high'}],
                           'defaultReasoningEffort': 'minimal'}], 'nextCursor': None if cursor else 'page-2'}
    else:
        raise RuntimeError('unexpected inference request')
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
''' % str(requests)
        with self.fake(code):
            result = models.codex_catalog()
        self.assertEqual([row['model'] for row in result], ['model-a', 'model-b'])
        self.assertEqual(result[0]['efforts'], ['minimal', 'high'])
        methods = [json.loads(line)['method'] for line in requests.read_text().splitlines()]
        self.assertEqual(methods, ['initialize', 'initialized', 'model/list', 'model/list'])

    def test_timeout_cleans_up_process(self):
        pid_file = self.home / 'pid'
        with self.fake('open(%r, "w").write(str(os.getpid()))\ntime.sleep(60)\n' % str(pid_file)):
            start = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'timed out'):
                models.codex_catalog(timeout=0.3)
            self.assertLess(time.monotonic() - start, 3)
        if os.name != 'nt':
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    @unittest.skipIf(os.name == 'nt', 'POSIX process-group cleanup')
    def test_exited_launcher_with_inherited_child_pipe_is_bounded(self):
        code = "import subprocess\nsubprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])\nsys.exit(0)\n"
        with self.fake(code):
            start = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'timed out'):
                models.codex_catalog(timeout=0.3)
            self.assertLess(time.monotonic() - start, 3)

    def test_errors_empty_malformed_and_repeated_cursor_fall_back(self):
        cases = ["{'error': {'message': 'SECRET'}}", "{'result': {'data': [], 'nextCursor': None}}",
                 "{'result': {'data': [] , 'nextCursor': 'repeat'}}", "{'result': {'wrong': []}}"]
        for response in cases:
            code = '''
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    response = {'result': {}} if request['method'] == 'initialize' else %s
    response['id'] = request['id']
    print(json.dumps(response), flush=True)
''' % response
            output = []
            with self.fake(code):
                entries = models.catalog(ROOT, 'codex', output.append)
            self.assertEqual(entries, models.fallback_catalog(ROOT, 'codex'))
            self.assertNotIn('SECRET', '\n'.join(output))
            self.assertIn('access unverified', '\n'.join(output))

    def test_claude_catalog_does_not_spawn_cli(self):
        with mock.patch.object(models.subprocess, 'Popen', side_effect=AssertionError('unexpected process')):
            self.assertEqual(len(models.catalog(ROOT, 'claude', lambda _: None)), 3)

    def test_server_exit_and_non_json_fall_back(self):
        for body in ['sys.exit(1)\n', 'print("not json", flush=True)\n']:
            with self.fake(body):
                result = models.catalog(ROOT, 'codex', lambda _: None)
            self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
