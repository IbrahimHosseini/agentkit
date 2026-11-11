"""Platform unit tests plus actual Windows process-boundary contracts."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from agentkit_core import platforms


class PlatformTests(unittest.TestCase):
    def test_posix_home_honors_home(self):
        with mock.patch.object(platforms, 'is_windows', return_value=False), mock.patch.dict(os.environ, {'HOME': 'posix-home'}):
            self.assertEqual(platforms.user_home(), Path('posix-home'))

    def test_simulated_windows_home_honors_userprofile(self):
        with mock.patch.object(platforms, 'is_windows', return_value=True), mock.patch.dict(os.environ, {'USERPROFILE': 'native-home'}):
            self.assertEqual(platforms.user_home(), Path('native-home'))

    def test_native_executable_argv_keeps_arguments_separate(self):
        arguments = ['tool', 'space value', '&echo.INJECTED', '%CANARY%', 'سلام']
        with mock.patch.object(platforms, 'is_windows', return_value=True), mock.patch.object(platforms, 'find_command', return_value='tool.exe'):
            self.assertEqual(platforms.command_args(arguments), ['tool.exe', *arguments[1:]])

    def test_simulated_cmd_rejects_unrepresentable_shell_arguments(self):
        # list2cmdline alone follows C-runtime rules, not CMD shell escaping.
        with mock.patch.object(platforms, 'is_windows', return_value=True), mock.patch.object(platforms, 'find_command', return_value='target.cmd'):
            for argument in ('&echo.INJECTED', '|echo.INJECTED', '<file', '>file', '^escape', '%CANARY%', '!CANARY!', 'bad\"argument', 'line\nbreak', 'line\rbreak'):
                with self.subTest(argument=argument):
                    with self.assertRaises(ValueError):
                        platforms.command_args(['target', argument])

    def test_simulated_cmd_boundary_keeps_shell_quotes_without_c_runtime_reescaping(self):
        executable = r'C:\tools with spaces\fake.cmd'
        with mock.patch.object(platforms, 'is_windows', return_value=True), mock.patch.object(platforms, 'find_command', return_value=executable):
            command = platforms.command_args(['fake', '--version'])
        self.assertIsInstance(command, str)
        self.assertTrue(command.endswith('/d /s /c ""' + executable + '" --version"'), command)
        self.assertNotIn('\\"', command)

    @unittest.skipUnless(os.name == 'nt', 'requires actual native Windows')
    def test_actual_cmd_launch_from_directory_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='agentkit-cmd-') as temp:
            root = Path(temp) / 'tools with spaces'
            root.mkdir()
            script = root / 'fake.cmd'
            script.write_bytes(b'@echo off\r\n@echo native-ok\r\n@exit /b 0\r\n')
            result = platforms.run([str(script), '--version'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), 'native-ok')

    @unittest.skipUnless(os.name == 'nt', 'requires actual native Windows')
    def test_actual_cmd_metacharacters_never_execute(self):
        with tempfile.TemporaryDirectory(prefix='agentkit-cmd-') as temp:
            script = Path(temp) / 'fake.cmd'
            script.write_bytes(b'@echo off\r\n@exit /b 0\r\n')
            for argument in ('&echo.INJECTED', '%AGENTKIT_CANARY%', '!AGENTKIT_CANARY!'):
                with self.subTest(argument=argument), self.assertRaises(ValueError):
                    platforms.run([str(script), argument], capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
