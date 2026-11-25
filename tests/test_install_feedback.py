"""Installation failures remain visible and cannot be masked by later stages."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from agentkit_core import desktop, platforms
from agentkit_core.cli import Lifecycle, parser


@unittest.skipIf(os.name == 'nt', 'POSIX integration contract')
class InstallFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agentkit-feedback-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'), CLAUDE_CONFIG_DIR=str(self.home / '.claude'), AGENTKIT_HOME=str(ROOT), AGENTKIT_LIBRARY_ONLY='1', PATH=str(self.bin) + os.pathsep + os.environ.get('PATH', ''), AGENTKIT_APPLICATION_DIRS=str(self.home / 'Applications'))
        self.stub('bun', 'exit 3')
        self.stub('claude', 'exit 0')
        self.stub('codex', 'exit 0')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)
        return path

    def run_shell(self, script):
        return subprocess.run(['bash', '-c', script], env=self.env, capture_output=True, text=True, timeout=20)

    def gstack(self, install, setup='exit 0', flags=''):
        clone = self.home / 'gstack'
        clone.mkdir()
        script = clone / 'setup'
        script.write_text('#!/bin/sh\n' + setup + '\n')
        script.chmod(0o755)
        return self.run_shell('set -- install; . "$AGENTKIT_HOME/lib/legacy-cli.sh"; parse_args --target codex --yes ' + flags + '; ui_init; resolve_target; set_target codex; TARGETS=codex; ' + install + '; step_gstack')

    def test_required_bun_declined_fails_with_reason(self):
        result = self.gstack('req_install() { echo "install declined" >&2; return 1; }')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Bun installation failed or was declined', result.stderr)
        self.assertIn('--skip gstack', result.stderr)

    def test_new_bun_available_in_same_process(self):
        install = '''req_install() { mkdir -p "$HOME/.bun/bin"; printf '#!/bin/sh\\nexit 0\\n' > "$HOME/.bun/bin/bun"; chmod +x "$HOME/.bun/bin/bun"; PATH="$HOME/.bun/bin:$PATH"; export PATH; }'''
        result = self.gstack(install, 'bun --version || exit 9')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('set up for codex', result.stdout)

    def test_setup_failure_reports_exit_and_log(self):
        self.stub('bun', 'exit 0')
        result = self.gstack('req_install() { exit 99; }', 'echo specific-setup-error; exit 17')
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertIn('exit 17', result.stderr)
        self.assertIn('log:', result.stderr)
        logs = list((self.home / '.codex/agentkit/logs').glob('*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('specific-setup-error', logs[0].read_text())

    def test_skip_gstack_does_not_install_bun(self):
        result = self.gstack('req_install() { echo SHOULD-NOT-INSTALL; return 99; }', flags='--skip gstack')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SHOULD-NOT-INSTALL', result.stdout)

    def test_declined_gstack_does_not_install_bun(self):
        result = self.gstack('ask() { return 1; }; req_install() { echo SHOULD-NOT-INSTALL; return 99; }')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SHOULD-NOT-INSTALL', result.stdout)

    def test_quiet_dependency_failure_keeps_specific_stdout_and_exit(self):
        result = self.run_shell('. "$AGENTKIT_HOME/lib/requirements.sh"; QUIET=1; req_run "Installing example" "echo exact-network-error; exit 23"')
        self.assertEqual(result.returncode, 23)
        self.assertIn('exact-network-error', result.stderr)
        self.assertIn('exit 23', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_progress_start_and_completion(self):
        result = self.run_shell('. "$AGENTKIT_HOME/lib/requirements.sh"; req_run "Installing example" "true"')
        self.assertEqual(result.returncode, 0)
        self.assertIn('Installing example ...', result.stdout)
        self.assertIn('Installing example: complete', result.stdout)

    def test_pipeline_download_failure_not_hidden_by_shell_success(self):
        result = self.run_shell('. "$AGENTKIT_HOME/lib/requirements.sh"; req_run "Remote script" "false | bash"')
        self.assertNotEqual(result.returncode, 0)

    def test_extras_failure_survives_summary(self):
        with mock.patch.dict(os.environ, self.env), mock.patch.object(desktop, 'discover', return_value={}):
            lifecycle = Lifecycle(parser().parse_args(['install', '--target', 'codex']))
            with mock.patch.object(platforms, 'run', return_value=subprocess.CompletedProcess([], 17)) as run:
                with self.assertRaisesRegex(ValueError, 'exit 17'):
                    lifecycle.posix_integration('extras')
            script = run.call_args.args[0][2]
            self.assertIn('step_gstack || rc=$?', script)
            self.assertIn('exit "$rc"', script)

    def test_piped_bootstrap_updates_existing_default_checkout_with_unset_home_override(self):
        checkout = self.home / '.agentkit'
        (checkout / '.git').mkdir(parents=True)
        (checkout / 'bin').mkdir()
        entry = checkout / 'bin/agentkit'
        entry.write_text('#!/bin/sh\nexit 0\n')
        entry.chmod(0o755)
        self.stub('git', 'if [ "$1" = --version ]; then echo "git version 2.54.0"; exit 0; fi; '
                  'if [ "$1" = -C ] && [ "$2" = "$HOME/.agentkit" ] && [ "$3" = pull ]; then echo correct-checkout; exit 0; fi; '
                  'echo "unexpected Git arguments: $*" >&2; exit 19')
        self.env.pop('AGENTKIT_HOME', None)
        self.env['ZDOTDIR'] = str(self.home)
        result = subprocess.run(['bash', '-s', '--', '--yes'], input=(ROOT / 'install.sh').read_text(), env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('correct-checkout', result.stdout)
        self.assertTrue((self.home / '.local/bin/agentkit').is_symlink())

    def test_required_cli_validation_cannot_be_bypassed(self):
        with mock.patch.dict(os.environ, dict(self.env, AGENTKIT_REQS_OK='1')), mock.patch.object(desktop, 'discover', return_value={'codex': desktop.App('ChatGPT', '/app')}):
            lifecycle = Lifecycle(parser().parse_args(['install', '--target', 'codex']))
            with mock.patch.object(platforms, 'run', return_value=subprocess.CompletedProcess([], 0)), mock.patch.object(platforms, 'command_error', return_value='--version failed (exit 7): broken installation'):
                with self.assertRaisesRegex(ValueError, 'broken installation'):
                    lifecycle.requirements()


if __name__ == '__main__':
    unittest.main()
