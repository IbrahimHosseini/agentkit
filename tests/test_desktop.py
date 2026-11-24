"""Offline desktop discovery, consent and installation failure contracts."""
import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from agentkit_core import desktop, platforms
from agentkit_core.cli import Lifecycle, parser


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agentkit-desktop-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home), 'USERPROFILE': str(self.home), 'AGENTKIT_APPLICATION_DIRS': str(self.home / 'Applications')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_windows_checklist_reads_arrow_and_confirmation_keys(self):
        msvcrt = mock.Mock()
        msvcrt.getwch.side_effect = ['\xe0', 'H', '\x00', 'P', ' ', '\r', '\x1b', '\x1a']
        with mock.patch.object(platforms, 'is_windows', return_value=True), \
             mock.patch.dict(sys.modules, {'msvcrt': msvcrt}), desktop.menu_keys(None) as read:
            self.assertEqual([read() for _ in range(6)],
                             ['up', 'down', 'toggle', 'enter', 'cancel', 'eof'])

    def bundle(self, name, identity, root=None):
        bundle = (root or self.home / 'Applications') / (name + '.app')
        (bundle / 'Contents/MacOS').mkdir(parents=True)
        (bundle / 'Contents/MacOS/app').touch()
        (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': identity, 'CFBundleExecutable': 'app'}))
        return bundle

    def test_mac_identity_accepts_successor_and_rejects_classic_and_named_directory(self):
        self.bundle('ChatGPT Classic', 'com.openai.chat')
        (self.home / 'Applications/Claude.app').mkdir()
        self.assertEqual(desktop.mac_apps(self.home), {})
        self.bundle('ChatGPT', 'com.openai.codex')
        self.assertEqual(desktop.mac_apps(self.home)['codex'].name, 'ChatGPT')

    def test_mac_discovery_continues_past_invalid_bundle_metadata(self):
        bad = self.bundle('Broken', 'com.openai.codex') / 'Contents/Info.plist'
        claude = self.bundle('Claude', 'com.anthropic.claudefordesktop')
        invalid_plists = (
            b'<?xml version="1.0"?><plist><dict>\x00</dict></plist>',
            plistlib.dumps(['not a bundle dictionary']),
            plistlib.dumps({'CFBundleIdentifier': 'com.openai.codex', 'CFBundleExecutable': 1}),
        )
        for contents in invalid_plists:
            with self.subTest(contents=contents):
                bad.write_bytes(contents)
                self.assertEqual(desktop.mac_apps(self.home), {'claude': desktop.App('Claude', str(claude))})

    def test_mac_system_and_user_roots_default(self):
        calls = []
        def record(root, pattern):
            calls.append(root)
            return []
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(Path, 'glob', record):
            desktop.mac_apps(self.home)
        self.assertEqual(calls, [self.home / 'Applications', Path('/Applications')])

    def test_mac_legacy_and_claude_require_executable(self):
        bundle = self.bundle('Codex', 'com.openai.codex')
        self.bundle('Claude', 'com.anthropic.claudefordesktop')
        self.assertEqual(set(desktop.mac_apps(self.home)), {'codex', 'claude'})
        (bundle / 'Contents/MacOS/app').unlink()
        self.assertNotIn('codex', desktop.mac_apps(self.home))

    def linux_entry(self, filename, name='Claude', executable='/usr/bin/true'):
        folder = self.home / 'Applications/applications'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_text('[Desktop Entry]\nType=Application\nName=' + name + '\nExec=' + executable + '\n')

    def test_linux_requires_identity_and_real_executable(self):
        self.linux_entry('random.desktop')
        self.linux_entry('com.openai.codex.desktop', 'Codex', '/missing/codex')
        self.assertEqual(desktop.linux_apps(self.home), {})
        self.linux_entry('claude-desktop.desktop')
        with mock.patch.object(desktop.shutil, 'which', side_effect=lambda p: p if p == '/usr/bin/true' else None):
            self.assertIn('claude', desktop.linux_apps(self.home))

    def test_linux_chatgpt_requires_package_record(self):
        self.linux_entry('chatgpt.desktop', 'ChatGPT')
        with mock.patch.object(desktop.shutil, 'which', return_value='/usr/bin/true'), mock.patch.object(desktop, 'linux_package', return_value=False):
            self.assertNotIn('codex', desktop.linux_apps(self.home))
        with mock.patch.object(desktop.shutil, 'which', return_value='/usr/bin/true'), mock.patch.object(desktop, 'linux_package', return_value=True):
            self.assertIn('codex', desktop.linux_apps(self.home))

    def test_package_query_timeout_does_not_crash_discovery(self):
        with mock.patch.object(desktop.shutil, 'which', return_value='/usr/bin/dpkg-query'), mock.patch.object(platforms, 'run', side_effect=subprocess.TimeoutExpired('dpkg-query', 10)):
            self.assertFalse(desktop.linux_package('chatgpt'))

    def test_windows_appx_identity_excludes_classic(self):
        record = json.dumps([{'Name': 'OpenAI.Codex', 'InstallLocation': str(self.home)}])
        with mock.patch.object(platforms, 'run', return_value=subprocess.CompletedProcess([], 0, record, '')):
            self.assertIn('codex', desktop.windows_apps())

    def test_unsupported_architecture(self):
        with mock.patch.object(desktop.platform, 'machine', return_value='riscv64'):
            self.assertIn('unsupported', desktop.support('codex'))

    def test_unsupported_linux_distribution(self):
        with mock.patch.object(desktop.sys, 'platform', 'linux'), mock.patch.object(platforms, 'is_windows', return_value=False), mock.patch.object(desktop.platform, 'machine', return_value='x86_64'), mock.patch.object(desktop, 'os_release', return_value={'ID': 'alpine', 'VERSION_ID': '3.22'}):
            self.assertIn('not officially supported', desktop.support('codex'))

    def test_claude_linux_desktop_is_disabled_independent_of_distribution_and_architecture(self):
        for arch in ('x86_64', 'aarch64', 'riscv64'):
            for release in ({'ID': 'ubuntu', 'VERSION_ID': '24.04'},
                            {'ID': 'debian', 'VERSION_ID': '13'},
                            {'ID': 'future-linux', 'VERSION_ID': '99'}):
                with self.subTest(arch=arch, release=release), \
                     mock.patch.object(desktop.sys, 'platform', 'linux'), \
                     mock.patch.object(platforms, 'is_windows', return_value=False), \
                     mock.patch.object(desktop.platform, 'machine', return_value=arch), \
                     mock.patch.object(desktop, 'os_release', return_value=release) as os_release:
                    self.assertEqual(desktop.support('claude'), 'Claude Desktop installation is disabled on Linux; Claude Code CLI is required')
                    os_release.assert_not_called()

    def test_claude_linux_install_has_no_external_or_interactive_effects(self):
        with mock.patch.object(desktop.sys, 'platform', 'linux'), \
             mock.patch.object(platforms, 'is_windows', return_value=False), \
             mock.patch.object(desktop.platform, 'machine', return_value='x86_64'), \
             mock.patch.object(desktop, 'os_release', return_value={'ID': 'ubuntu', 'VERSION_ID': '24.04'}), \
             mock.patch.object(desktop, 'download') as download, \
             mock.patch.object(desktop, 'command') as command, \
             mock.patch.object(desktop.webbrowser, 'open') as browser, \
             mock.patch.object(desktop, 'answer') as answer, \
             mock.patch.object(desktop, 'discover') as discover:
            with self.assertRaisesRegex(ValueError, 'disabled on Linux'):
                desktop.install('claude', lambda _: None)
            for effect in (download, command, browser, answer, discover):
                effect.assert_not_called()

    def test_desktop_support_preserves_other_platforms_and_codex_linux(self):
        cases = [('darwin', False, 'arm64', {}, 'claude'),
                 ('win32', True, 'x86_64', {}, 'claude'),
                 ('linux', False, 'x86_64', {'ID': 'ubuntu', 'VERSION_ID': '24.04'}, 'codex'),
                 ('linux', False, 'aarch64', {'ID': 'arch'}, 'codex')]
        for system, windows, arch, release, target in cases:
            with self.subTest(system=system, target=target, release=release), \
                 mock.patch.object(desktop.sys, 'platform', system), \
                 mock.patch.object(platforms, 'is_windows', return_value=windows), \
                 mock.patch.object(desktop.platform, 'machine', return_value=arch), \
                 mock.patch.object(desktop, 'os_release', return_value=release):
                self.assertEqual(desktop.support(target), '')

    def lifecycle(self, args):
        with mock.patch.object(desktop, 'discover', return_value={}):
            return Lifecycle(parser().parse_args(['install'] + args))

    def test_auto_targets_union_desktop_and_cli(self):
        lifecycle = self.lifecycle([])
        lifecycle.apps = {'codex': desktop.App('ChatGPT', '/app')}
        with mock.patch.object(platforms, 'find_command', side_effect=lambda t: '/bin/claude' if t == 'claude' else None):
            self.assertEqual(lifecycle.targets(), ['claude', 'codex'])

    def test_yes_does_not_authorize_desktop_install(self):
        lifecycle = self.lifecycle(['--target', 'codex', '--yes'])
        with mock.patch.object(desktop, 'support', return_value=''), mock.patch.object(desktop, 'terminal') as terminal, mock.patch.object(desktop, 'answer', return_value='n'), mock.patch.object(desktop, 'install') as install:
            terminal.return_value.__enter__.return_value = io.StringIO()
            lifecycle.desktop_installations()
            install.assert_not_called()
        self.assertEqual(lifecycle.rows[-1], ('codex', 'desktop', 'skipped'))

    def test_claude_linux_and_wsl_lifecycle_never_offers_desktop(self):
        for wsl in (False, True):
            for flags in ([], ['--yes'], ['--dry-run']):
                with self.subTest(wsl=wsl, flags=flags), \
                     mock.patch.dict(os.environ, {'WSL_DISTRO_NAME': 'Ubuntu' if wsl else '', 'WSL_INTEROP': '/run/WSL/interop' if wsl else ''}), \
                     mock.patch.object(desktop.sys, 'platform', 'linux'), \
                     mock.patch.object(platforms, 'is_windows', return_value=False), \
                     mock.patch.object(desktop.platform, 'machine', return_value='x86_64'), \
                     mock.patch.object(desktop, 'os_release', return_value={'ID': 'ubuntu', 'VERSION_ID': '24.04'}), \
                     mock.patch.object(desktop, 'terminal') as terminal, \
                     mock.patch.object(desktop, 'answer') as answer, \
                     mock.patch.object(desktop, 'install') as install, \
                     mock.patch.object(desktop, 'download') as download, \
                     mock.patch.object(desktop, 'command') as command, \
                     mock.patch.object(desktop.webbrowser, 'open') as browser:
                    lifecycle = self.lifecycle(['--target', 'claude'] + flags)
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        lifecycle.desktop_installations()
                    for effect in (terminal, answer, install, download, command, browser):
                        effect.assert_not_called()
                    self.assertNotIn('Would offer', output.getvalue())

    def test_noninteractive_skips_desktop(self):
        lifecycle = self.lifecycle(['--target', 'claude', '--yes'])
        with mock.patch.object(desktop, 'support', return_value=''), mock.patch.object(desktop, 'terminal') as terminal, mock.patch.object(desktop, 'install') as install:
            terminal.return_value.__enter__.return_value = None
            lifecycle.desktop_installations()
            install.assert_not_called()

    def test_windows_redirected_input_does_not_reopen_console(self):
        with mock.patch.object(platforms, 'is_windows', return_value=True), \
             mock.patch('sys.stdin.isatty', return_value=False), \
             mock.patch('builtins.open') as opened:
            with desktop.terminal() as stream:
                self.assertIsNone(stream)
            opened.assert_not_called()

    def test_windows_interactive_input_keeps_console(self):
        with mock.patch.object(platforms, 'is_windows', return_value=True), \
             mock.patch('sys.stdin.isatty', return_value=True), \
             mock.patch.object(desktop, 'windows_console_input', return_value=True), \
             mock.patch('builtins.open') as opened:
            with desktop.terminal() as stream:
                self.assertIs(stream, sys.stdin)
            opened.assert_not_called()

    def test_windows_character_device_without_console_is_noninteractive(self):
        with mock.patch.object(platforms, 'is_windows', return_value=True), \
             mock.patch('sys.stdin.isatty', return_value=True), \
             mock.patch.object(desktop, 'windows_console_input', return_value=False), \
             mock.patch('builtins.open') as opened:
            with desktop.terminal() as stream:
                self.assertIsNone(stream)
            opened.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'requires Windows console handles')
    def test_windows_nul_handle_is_not_a_console(self):
        with open(os.devnull) as stream:
            self.assertFalse(desktop.windows_console_input(stream))

    def test_dry_run_never_downloads_or_prompts(self):
        lifecycle = self.lifecycle(['--target', 'claude', '--dry-run'])
        with mock.patch.object(desktop, 'support', return_value=''), mock.patch.object(desktop, 'answer') as answer, mock.patch.object(desktop, 'install') as install:
            lifecycle.desktop_installations()
            answer.assert_not_called()
            install.assert_not_called()

    def test_accepted_desktop_failure_not_successful(self):
        lifecycle = self.lifecycle(['--target', 'claude'])
        with mock.patch.object(desktop, 'support', return_value=''), mock.patch.object(desktop, 'terminal') as terminal, mock.patch.object(desktop, 'answer', return_value='y'), mock.patch.object(desktop, 'install', side_effect=ValueError('download failed')):
            terminal.return_value.__enter__.return_value = io.StringIO()
            with self.assertRaisesRegex(ValueError, 'download failed'):
                lifecycle.desktop_installations()
        self.assertEqual(lifecycle.rows[-1][-1], 'failed')

    def test_quiet_command_failure_retains_output(self):
        def fail(args, **kwargs):
            kwargs['stdout'].write('specific download error')
            return subprocess.CompletedProcess(args, 7)
        output = io.StringIO()
        with mock.patch.object(platforms, 'run', side_effect=fail), contextlib.redirect_stderr(output):
            with self.assertRaisesRegex(ValueError, 'exit 7'):
                desktop.command('Download', ['fake'], lambda _: None, quiet=True)
        self.assertIn('specific download error', output.getvalue())

    def test_download_failure_is_reported_with_original_reason(self):
        with mock.patch.object(desktop, 'support', return_value=''), mock.patch.object(desktop.sys, 'platform', 'darwin'), mock.patch.object(desktop, 'download', side_effect=OSError('network unreachable')):
            with self.assertRaisesRegex(ValueError, 'network unreachable'):
                desktop.install('codex', lambda _: None)

    def test_manual_install_launch_is_not_success(self):
        with mock.patch.object(desktop, 'support', return_value=''), mock.patch.object(desktop.sys, 'platform', 'linux'), mock.patch.object(desktop, 'os_release', return_value={'ID': 'arch'}), mock.patch.object(desktop.webbrowser, 'open', return_value=True), mock.patch.object(desktop, 'answer', return_value=''), mock.patch.object(desktop, 'discover', return_value={}):
            with self.assertRaisesRegex(ValueError, 'could not be verified'):
                desktop.install('codex', lambda _: None)

    def test_success_rechecks_desktop(self):
        with mock.patch.object(desktop, 'support', return_value=''), mock.patch.object(desktop.sys, 'platform', 'linux'), mock.patch.object(desktop, 'os_release', return_value={'ID': 'arch'}), mock.patch.object(desktop.webbrowser, 'open', return_value=True), mock.patch.object(desktop, 'discover', return_value={'codex': desktop.App('ChatGPT', '/app')}):
            output = []
            desktop.install('codex', output.append)
        self.assertIn('installed and verified', output[-1])


if __name__ == '__main__':
    unittest.main()
