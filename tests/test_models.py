"""Model selection contracts: temporary homes, offline catalogs and fake CLIs."""
import hashlib
import re
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
        with mock.patch('sys.stdin.isatty', return_value=True), \
             mock.patch.object(models.desktop, 'windows_console_input', return_value=True), \
             mock.patch.object(models, 'catalog',
                side_effect=lambda root, target, say, **kw: models.fallback_catalog(root, target)):
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

    def test_windows_nul_input_does_not_prompt_for_models(self):
        life, _ = self.seed()
        before = tree(self.home)
        with mock.patch('sys.stdin.isatty', return_value=True), \
             mock.patch.object(models.platforms, 'is_windows', return_value=True), \
             mock.patch.object(models.desktop, 'windows_console_input', return_value=False), \
             mock.patch.object(models, 'catalog') as discover:
            read = mock.Mock(side_effect=AssertionError('unexpected prompt'))
            self.assertIsNone(models.configure(life, read=read))
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

    def test_target_selection_precedes_gather_and_leaves_other_home_untouched(self):
        life = self.lifecycle('models', '--agent', 'backend')
        self.seed('claude', life=life)
        self.seed('codex', life=life)
        before = tree(life.homes['codex'])
        original = models.load_preferences
        queried = []
        def preferences(home):
            queried.append(home)
            self.assertEqual(home, life.homes['claude'])
            return original(home)
        with mock.patch.object(models, 'load_preferences', side_effect=preferences):
            models.commit(life, self.batch(life, ['1', 'y', '1', '2', 'y']))
        self.assertTrue(queried)
        self.assertEqual(tree(life.homes['codex']), before)
        self.assertLess(self.output.getvalue().index('Choose model settings target'),
                        self.output.getvalue().index('Target  Agent'))

    def test_target_cancel_and_eof_never_gather(self):
        life = self.lifecycle('models')
        self.seed('claude', life=life)
        self.seed('codex', life=life)
        before = tree(self.home)
        for answer in ['0', EOFError()]:
            with mock.patch.object(models, 'gather', side_effect=AssertionError('must select first')):
                self.assertIsNone(self.batch(life, [answer]))
        self.assertEqual(tree(self.home), before)

    def test_terminal_model_picker_shows_proposal_and_preserves_files_on_cancel(self):
        life = self.lifecycle('models', '--target', 'both', '--agent', 'backend')
        self.seed('claude', life=life)
        self.seed('codex', life=life)
        before = tree(self.home)
        with mock.patch.object(self.output, 'isatty', return_value=True), \
             mock.patch.dict(os.environ, TERM='xterm-256color', NO_COLOR='1', COLUMNS='100'):
            batch = self.batch(life, ['y', '1', '2', '1', '1', 'n'])
        self.assertIsNone(batch)
        self.assertEqual(tree(self.home), before)
        output = self.output.getvalue()
        self.assertIn('│ Model ID', output)
        self.assertIn('│ Effort ', output)
        proposal = output.split('Proposed model settings:', 1)[1]
        self.assertRegex(proposal, r'│ claude\s+│ backend\s+│ opus\s+│ medium\s+│')
        self.assertRegex(proposal, r'│ codex\s+│ backend\s+│ gpt-6\.1-sol\s+│ high\s+│')
        self.assertIn('Model changes cancelled.', proposal)
        self.assertNotIn('\x1b', output)

    def test_install_model_subset_does_not_change_installation_targets(self):
        life = self.lifecycle('install', '--target', 'both')
        life.args.agent = 'backend'
        self.seed('claude', life=life)
        self.seed('codex', life=life)
        before = tree(life.homes['codex'])
        batch = self.batch(life, ['1', 'y', '1', '2', 'y'], installing=True)
        self.assertEqual(life.targets(), ['claude', 'codex'])
        models.commit(life, batch)
        self.assertEqual(tree(life.homes['codex']), before)

    def test_selected_linked_backups_rejected_unselected_ignored(self):
        life = self.lifecycle('models', '--agent', 'backend')
        self.seed('claude', life=life)
        self.seed('codex', life=life)
        backups = life.homes['codex'] / 'agentkit/backups'
        outside = self.home / 'outside-backups'
        outside.mkdir()
        try:
            backups.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlink privileges unavailable')
        self.assertIsNone(self.batch(life, ['1', 'n']))
        with self.assertRaisesRegex(ValueError, 'linked state'):
            self.batch(life, ['2'])

    def test_dry_run_claude_skips_runtime_install(self):
        life, _ = self.seed()
        life.args.dry_run = True
        with mock.patch('sys.stdin.isatty', return_value=True), \
             mock.patch.object(models, 'bounded_run', side_effect=AssertionError('runtime mutation')):
            self.assertIsNone(models.configure(life, read=mock.Mock(side_effect=['y', '', '', 'n'])))
        self.assertFalse((life.homes['claude'] / 'agentkit/runtime').exists())

    def test_safe_new_effort_persists_and_updates_both_formats(self):
        for target in ['claude', 'codex']:
            life, dest = self.seed(target)
            row, states = models.gather(life, False)
            models.commit(life, (row, states, {(target, 'backend'): {'model': 'future', 'effort': 'ultra'}}))
            self.assertEqual(models.read_choice(dest.read_bytes(), target)['effort'], 'ultra')
            self.assertEqual(models.load_preferences(life.homes[target])['backend']['effort'], 'ultra')
            life.current = target
            life.args.skip = ['skills', 'claude-md']
            life.args.yes = True
            life.sync('update')
            self.assertEqual(models.read_choice(dest.read_bytes(), target)['effort'], 'ultra')
        for effort in ['bad\neffort', 'a b', '', '"escape']:
            with self.assertRaises(ValueError):
                models.validate_choice({'model': 'future', 'effort': effort})

    def test_show_all_replaces_choices_and_labels_hidden(self):
        entries = [{'model': 'visible', 'name': 'Visible', 'efforts': [], 'default': None}]
        hidden = {'model': 'hidden', 'name': 'Hidden name', 'hidden': True, 'efforts': ['ultra'], 'default': None}
        fetch = mock.Mock(return_value=entries + [hidden])
        choice = models.choose({'model': 'visible', 'effort': None}, {'model': 'visible', 'effort': None},
                               entries, print, mock.Mock(side_effect=['a', '2', '1']), fetch)
        self.assertEqual(choice, {'model': 'hidden', 'effort': 'ultra'})
        fetch.assert_called_once_with()
        self.assertIn('Hidden name [hidden] (hidden)', self.output.getvalue())


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
            self.assertEqual(entries[:len(models.fallback_catalog(ROOT, 'codex'))], models.fallback_catalog(ROOT, 'codex'))
            self.assertNotIn('SECRET', '\n'.join(output))
            self.assertIn('access unverified', '\n'.join(output))

    def test_claude_catalog_without_runtime_home_falls_back(self):
        with mock.patch.object(models.subprocess, 'Popen', side_effect=AssertionError('unexpected process')), \
             mock.patch.object(models, 'openai_entries', return_value=[]):
            self.assertEqual(len(models.catalog(ROOT, 'claude', lambda _: None)), 3)

    def test_claude_catalog_adds_openai_relay_models(self):
        relay = [{'model': 'gpt-x', 'name': 'gpt-x', 'efforts': ['high'], 'default': 'high', 'hidden': False,
                  'source': 'Codex CLI (relay)', 'status': 'reported'}]
        with mock.patch.object(models, 'codex_catalog', return_value=relay + [dict(relay[0], model='other-model')]):
            found = models.openai_entries(ROOT, lambda _: None)
        self.assertEqual([item['model'] for item in found], ['gpt-x'])
        with mock.patch.object(models, 'codex_catalog', side_effect=ValueError('no codex')):
            output = []
            found = models.openai_entries(ROOT, output.append)
        self.assertTrue(found and all(models.is_openai(item['model']) for item in found))
        self.assertIn('unverified', ' '.join(output))

    def test_openai_model_relays_through_codex_and_restores(self):
        for path in sorted((ROOT / 'agents').glob('*.md')):
            original = path.read_bytes()
            base = models.patch_agent(original, 'claude', {'model': 'sonnet', 'effort': None})
            relay = models.patch_agent(base, 'claude', {'model': 'gpt-6.1-sol', 'effort': 'high'})
            text = relay.decode('utf-8')
            fm, body = codex.parse_md(text, 'x')
            self.assertEqual(fm['model'], 'sonnet')
            self.assertNotIn('effort', fm)
            self.assertIn('Bash', fm['tools'])
            self.assertIn('codex exec', body)
            self.assertIn('-m gpt-6.1-sol', body)
            self.assertEqual(models.read_choice(relay, 'claude'), {'model': 'gpt-6.1-sol', 'effort': 'high'})
            # Switching model never stacks a second block.
            again = models.patch_agent(relay, 'claude', {'model': 'gpt-6-luna', 'effort': None})
            self.assertEqual(again.count(b'agentkit:codex:start'), 1)
            self.assertEqual(models.read_choice(again, 'claude'), {'model': 'gpt-6-luna', 'effort': None})
            self.assertNotIn(b'model_reasoning_effort', again)
            # Back to a Claude model restores the original tools and body.
            self.assertEqual(models.patch_agent(again, 'claude', {'model': 'sonnet', 'effort': None}), base)

    def test_claude_relay_round_trip_preserves_body_spacing(self):
        for newline in ('\n', '\r\n'):
            for blank_lines in (0, 1, 3):
                with self.subTest(newline=newline, blank_lines=blank_lines):
                    header = newline.join(('---', 'name: sample', 'description: A test agent',
                                           'tools: Read', 'model: sonnet', '---', ''))
                    body = newline * blank_lines + '# Keep this heading' + newline
                    original = (header + body).encode('utf-8')
                    updated = original
                    for model in ('gpt-6.1-sol', 'gpt-6-luna', 'sonnet'):
                        updated = models.patch_agent(updated, 'claude', {'model': model, 'effort': None})
                    self.assertEqual(updated, original)

    def test_legacy_openai_model_without_relay_is_repaired(self):
        legacy = (ROOT / 'agents/backend.md').read_text(encoding='utf-8').replace('model: sonnet', 'model: gpt-6.2-sol').encode()
        choice = models.read_choice(legacy, 'claude')
        self.assertEqual(choice, {'model': 'gpt-6.2-sol', 'effort': None})
        fixed = models.patch_agent(legacy, 'claude', choice)
        fm, body = codex.parse_md(fixed.decode(), 'x')
        self.assertEqual(fm['model'], 'sonnet')
        self.assertIn('-m gpt-6.2-sol', body)
        self.assertNotIn('model_reasoning_effort', body)

    def test_relay_sandbox_follows_agent_tools(self):
        reader = (ROOT / 'agents/security.md').read_bytes()
        writer = (ROOT / 'agents/backend.md').read_bytes()
        choice = {'model': 'gpt-6.1-sol', 'effort': 'high'}
        self.assertIn(b'-s read-only', models.patch_agent(reader, 'claude', choice))
        self.assertIn(b'-s workspace-write', models.patch_agent(writer, 'claude', choice))


    def render_codex(self, name):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / (name + '.toml')
            codex.render_agent(str(ROOT / 'agents' / (name + '.md')), str(ROOT / 'codex/models.map'),
                               str(ROOT / 'codex/karpathy-guidelines.md'), str(out))
            return out.read_bytes()

    def test_codex_agent_relays_to_claude_and_restores(self):
        original = self.render_codex('backend')
        choice = {'model': 'opus', 'effort': 'high'}
        relayed = models.patch_agent(original, 'codex', choice)
        text = relayed.decode()
        codex.validate_toml(text, 'relay')
        self.assertIn('claude -p --model opus --effort high --permission-mode acceptEdits --allowedTools Bash', text)
        self.assertIn('sandbox_mode = "danger-full-access"', text)
        self.assertEqual(models.read_choice(relayed, 'codex'), choice)
        # The host keeps the Codex model the agent had before.
        self.assertEqual(re.search(r'^model = (.+)$', text, re.M).group(1),
                         re.search(r'^model = (.+)$', original.decode(), re.M).group(1))
        # Changing the Claude model keeps the original host; leaving restores every byte.
        again = models.patch_agent(relayed, 'codex', {'model': 'sonnet', 'effort': None})
        self.assertIn('claude -p --model sonnet --permission-mode', again.decode())
        back = models.patch_agent(again, 'codex', models.read_choice(original, 'codex'))
        self.assertEqual(back, models.patch_agent(original, 'codex', models.read_choice(original, 'codex')))
        self.assertNotIn('agentkit:claude', back.decode())

    def test_codex_relay_sandbox_follows_agent_tools(self):
        reader = models.patch_agent(self.render_codex('security'), 'codex', {'model': 'opus', 'effort': None})
        self.assertIn('--permission-mode plan', reader.decode())
        self.assertNotIn('--allowedTools', reader.decode())

    def test_codex_catalog_adds_claude_relay_models(self):
        entries = models.catalog(ROOT, 'codex', lambda _: None)
        self.assertTrue({'opus', 'sonnet', 'haiku'} <= {item['model'] for item in entries})

    def test_codex_hidden_new_effort_and_missing_capabilities(self):
        code = """
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request: continue
    rows = [{'model': 'future', 'displayName': 'Future', 'supportedReasoningEfforts': [{'reasoningEffort': 'ultra'}], 'defaultReasoningEffort': 'ultra'},
            {'model': 'unknown', 'displayName': {}, 'defaultReasoningEffort': 'high'},
            {'model': 'hidden', 'hidden': True}]
    result = {} if request['method'] == 'initialize' else {'data': rows, 'nextCursor': None}
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
"""
        with self.fake(code):
            visible = models.codex_catalog()
            all_rows = models.codex_catalog(include_hidden=True)
        self.assertEqual([row['model'] for row in visible], ['future', 'unknown'])
        self.assertEqual(visible[0]['efforts'], ['ultra'])
        self.assertEqual(visible[1]['name'], 'unknown')
        self.assertEqual(visible[1]['default'], None)
        self.assertEqual(visible[1]['efforts'], [])
        self.assertTrue(all_rows[-1]['hidden'])

    def test_claude_missing_dependencies_and_setup_failure(self):
        home = self.home / '.claude'
        for available, expected in [({}, 'Node.js is missing'),
                                    ({'node': '/node'}, 'CLI is missing'),
                                    ({'node': '/node', 'claude': '/claude'}, 'npm is missing')]:
            with mock.patch.object(models.platforms, 'find_command', side_effect=lambda name: available.get(name)), \
                 mock.patch.object(models, 'openai_entries', return_value=[]):
                output = []
                rows = models.catalog(ROOT, 'claude', output.append, home=home)
                self.assertEqual(rows, models.fallback_catalog(ROOT, 'claude'))
                self.assertIn(expected, ' '.join(output))
                self.assertIn('Local fallback', ' '.join(output))
        with mock.patch.object(models.platforms, 'find_command', side_effect=lambda name: '/' + name), \
             mock.patch.object(models, 'bounded_run', side_effect=ValueError('SDK setup failed; check npm network')):
            output = []
            models.catalog(ROOT, 'claude', output.append, home=home)
            self.assertIn('SDK setup failed', ' '.join(output))

    def test_claude_normalizes_capabilities_and_bounds_setup(self):
        home = self.home / '.claude'
        raw = [{'value': 'new', 'displayName': 'New', 'supportedEffortLevels': ['ultra']},
               {'value': 'unknown', 'supportsEffort': True}]
        with mock.patch.object(models.platforms, 'find_command', side_effect=lambda name: '/' + name), \
             mock.patch.object(models, 'bounded_run', side_effect=[b'', json.dumps(raw).encode()]) as run:
            entries = models.claude_catalog(ROOT, home)
        self.assertEqual(entries[0]['efforts'], ['ultra'])
        self.assertEqual(entries[1]['efforts'], [])
        self.assertEqual(entries[1]['default'], None)
        self.assertEqual(run.call_count, 2)
        self.assertIn('--ignore-scripts', run.call_args_list[0][0][0])
        self.assertIn('--omit=optional', run.call_args_list[0][0][0])
        self.assertTrue(all(call[0][1] <= 10 for call in run.call_args_list))
        self.assertEqual(run.call_args_list[0][0][2], home / 'agentkit/runtime/claude-catalog')

    def test_partial_failed_sdk_install_retries_until_success_marker(self):
        home = self.home / '.claude'
        runtime = home / 'agentkit/runtime/claude-catalog'
        sdk = runtime / 'node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs'
        raw = json.dumps([{'value': 'new'}]).encode()
        calls = []
        def partial(args, timeout, cwd=None, **kwargs):
            calls.append(args)
            sdk.parent.mkdir(parents=True, exist_ok=True)
            sdk.write_text('partial installation')
            raise ValueError('Claude SDK setup failed; check npm network/registry access and retry')
        with mock.patch.object(models.platforms, 'find_command', side_effect=lambda name: '/' + name):
            with mock.patch.object(models, 'bounded_run', side_effect=partial):
                with self.assertRaisesRegex(ValueError, 'setup failed'):
                    models.claude_catalog(ROOT, home)
            self.assertFalse((runtime / '.installed-lock-sha256').exists())
            with mock.patch.object(models, 'bounded_run', side_effect=[b'', raw]) as run:
                self.assertEqual(models.claude_catalog(ROOT, home)[0]['model'], 'new')
            self.assertEqual(run.call_args_list[0][0][0][1], 'ci')
            self.assertTrue((runtime / '.installed-lock-sha256').exists())
            with mock.patch.object(models, 'bounded_run', return_value=raw) as run:
                models.claude_catalog(ROOT, home)
                self.assertEqual(run.call_count, 1)
                self.assertNotIn('ci', run.call_args[0][0])

    def test_claude_malformed_catalog_falls_back(self):
        for raw in [{}, [], [{'value': 'x', 'supportedEffortLevels': 'high'}],
                    [{'value': 'x', 'supportedEffortLevels': False}],
                    [{'value': 'x', 'supportedEffortLevels': {}}], [{'value': 'bad id'}]]:
            with mock.patch.object(models, 'bounded_run', side_effect=[b'', json.dumps(raw).encode()]), \
                 mock.patch.object(models, 'openai_entries', return_value=[]), \
                 mock.patch.object(models.platforms, 'find_command', side_effect=lambda name: '/' + name):
                output = []
                self.assertEqual(models.catalog(ROOT, 'claude', output.append, home=self.home / '.claude'),
                                 models.fallback_catalog(ROOT, 'claude'))

    def test_claude_helper_fake_sdk_contract(self):
        import shutil
        if not shutil.which('node'):
            self.skipTest('Node not installed; optional helper')
        proc = subprocess.run(['node', str(ROOT / 'lib/claude_catalog/discover.test.mjs')],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('no user messages or inference', proc.stdout)

    def test_nonzero_npm_reports_setup_remedy_without_provider_output(self):
        with self.fake('print("PRIVATE PROVIDER DETAIL"); sys.exit(7)\n'):
            with self.assertRaisesRegex(ValueError, 'setup failed; check npm network/registry access and retry') as error:
                models.bounded_run(['npm', 'ci'], 1, stage='setup')
        self.assertNotIn('PRIVATE', str(error.exception))

    def test_bounded_helper_timeout_reaps_tree(self):
        with self.fake('time.sleep(60)\n'):
            start = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'timed out'):
                models.bounded_run(['node', 'ignored'], 0.2)
            self.assertLess(time.monotonic() - start, 3)

    def test_server_exit_and_non_json_fall_back(self):
        for body in ['sys.exit(1)\n', 'print("not json", flush=True)\n']:
            with self.fake(body):
                result = models.catalog(ROOT, 'codex', lambda _: None)
            self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
