"""Bounded desktop discovery and explicitly consented official installers.

Sources: claude.com/download,
learn.chatgpt.com/docs/app and its Linux/Windows installation pages.
Desktop presence is informational; CLI readiness is checked separately.
"""
import contextlib
import configparser
import json
import os
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from . import platforms

PAGES = {'claude': 'https://claude.com/download', 'codex': 'https://chatgpt.com/download/'}
BUNDLE_IDS = {'claude': 'com.anthropic.claudefordesktop', 'codex': 'com.openai.codex'}


@dataclass
class App:
    name: str
    path: str


def mac_apps(home: Path) -> Dict[str, App]:
    found = {}
    roots = [Path(p) for p in os.environ['AGENTKIT_APPLICATION_DIRS'].split(os.pathsep) if p] if 'AGENTKIT_APPLICATION_DIRS' in os.environ else [home / 'Applications', Path('/Applications')]
    for root in roots:
        for bundle in root.glob('*.app'):
            try:
                info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
                for target, identity in BUNDLE_IDS.items():
                    executable = info.get('CFBundleExecutable', '')
                    if info.get('CFBundleIdentifier') == identity and executable and (bundle / 'Contents/MacOS' / executable).is_file():
                        found.setdefault(target, App(bundle.stem, str(bundle)))
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
    return found


def windows_apps() -> Dict[str, App]:
    found = {}
    # AppX package identity distinguishes the new Codex app from ChatGPT Classic.
    script = ('Get-AppxPackage | Where-Object { $_.Name -eq "OpenAI.Codex" -or $_.Name -eq "Claude" } | '
              'Select-Object Name,InstallLocation | ConvertTo-Json -Compress')
    try:
        result = platforms.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=15)
        records = json.loads(result.stdout or '[]') if not result.returncode else []
        if isinstance(records, dict):
            records = [records]
        for record in records:
            location = Path(record.get('InstallLocation') or '')
            if record.get('InstallLocation') and location.is_dir():
                target = 'codex' if record['Name'] == 'OpenAI.Codex' else 'claude'
                found[target] = App('ChatGPT (Codex)' if target == 'codex' else 'Claude', str(location))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for base in (r'Software\Microsoft\Windows\CurrentVersion\Uninstall', r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
                try:
                    with winreg.OpenKey(hive, base) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            with winreg.OpenKey(key, winreg.EnumKey(key, i)) as entry:
                                def value(name):
                                    try:
                                        return str(winreg.QueryValueEx(entry, name)[0])
                                    except OSError:
                                        return ''
                                name, publisher, location = value('DisplayName'), value('Publisher'), value('InstallLocation')
                                target = 'claude' if name == 'Claude' and 'Anthropic' in publisher else 'codex' if name == 'Codex' and 'OpenAI' in publisher else None
                                if target and location and Path(location).is_dir():
                                    found.setdefault(target, App(name, location))
                except OSError:
                    continue
    except ImportError:
        pass
    return found


def linux_apps(home: Path) -> Dict[str, App]:
    found = {}
    roots = [Path(os.environ.get('XDG_DATA_HOME', home / '.local/share'))]
    roots += [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]
    if 'AGENTKIT_APPLICATION_DIRS' in os.environ:
        roots = [Path(p) for p in os.environ['AGENTKIT_APPLICATION_DIRS'].split(os.pathsep) if p]
    # Exact desktop identities and a real launchable executable; a directory or
    # display name alone is not evidence of an installed desktop app.
    identities = {'com.anthropic.claudefordesktop.desktop': 'claude', 'claude-desktop.desktop': 'claude',
                  'com.openai.codex.desktop': 'codex', 'codex.desktop': 'codex', 'chatgpt.desktop': 'codex'}
    for root in roots:
        for filename, target in identities.items():
            path = root / 'applications' / filename
            try:
                config = configparser.ConfigParser(interpolation=None)
                config.read(path, encoding='utf-8')
                entry = config['Desktop Entry']
                if entry.get('Type') != 'Application' or entry.get('Hidden', '').lower() == 'true':
                    continue
                command = shlex.split(entry.get('Exec', ''))
                if not command:
                    continue
                executable = shutil.which(command[0])
                if not executable:
                    continue
                # Classic never used the Codex identity. For the renamed app,
                # require the official package record, not only ChatGPT's name.
                if filename == 'chatgpt.desktop' and not linux_package('chatgpt'):
                    continue
                found.setdefault(target, App(entry.get('Name', target), str(path)))
            except (OSError, ValueError, KeyError, configparser.Error):
                continue
    return found


def _linux_package(name: str) -> bool:
    if shutil.which('dpkg-query'):
        result = platforms.run(['dpkg-query', '-W', '-f=${Status}', name], capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and result.stdout.strip() == 'install ok installed'
    if shutil.which('rpm'):
        return platforms.run(['rpm', '-q', name], capture_output=True, timeout=10).returncode == 0
    if shutil.which('pacman'):
        return platforms.run(['pacman', '-Q', name], capture_output=True, timeout=10).returncode == 0
    return False


def linux_package(name: str) -> bool:
    try:
        return _linux_package(name)
    except (OSError, subprocess.TimeoutExpired):
        return False


def windows_console_input(stream):
    """NUL is a character device: Windows isatty alone does not imply a console."""
    try:
        import ctypes
        import msvcrt
        mode = ctypes.c_ulong()
        get_mode = ctypes.WinDLL('kernel32', use_last_error=True).GetConsoleMode
        get_mode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        get_mode.restype = ctypes.c_int
        return bool(get_mode(msvcrt.get_osfhandle(stream.fileno()), ctypes.byref(mode)))
    except (ImportError, AttributeError, OSError, ValueError):
        return False


@contextlib.contextmanager
def terminal():
    if platforms.is_windows():
        # Do not reopen CONIN$ for redirected input, or treat NUL as a console.
        yield sys.stdin if sys.stdin.isatty() and windows_console_input(sys.stdin) else None
        return
    if sys.stdin.isatty():
        yield sys.stdin
        return
    try:
        stream = open('/dev/tty', 'r')
    except OSError:
        yield None
        return
    with stream:
        yield stream


def answer(prompt: str) -> str:
    with terminal() as stream:
        if stream is None:
            raise ValueError('interactive confirmation is unavailable; rerun in a terminal')
        print(prompt, end='', flush=True)
        value = stream.readline()
        if not value:
            raise ValueError('confirmation input ended; installation was not confirmed')
        return value.strip()


def discover(home: Optional[Path] = None) -> Dict[str, App]:
    home = home or platforms.user_home()
    if sys.platform == 'darwin':
        return mac_apps(home)
    if platforms.is_windows():
        return windows_apps()
    if sys.platform.startswith('linux'):
        return linux_apps(home)
    return {}


def os_release() -> Dict[str, str]:
    try:
        return dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().replace('"', '').splitlines() if '=' in line)
    except OSError:
        return {}


def support(target: str) -> str:
    # Product policy, independent of current or future vendor Linux support.
    # WSL runs this Linux path too; Claude Code remains a separate requirement.
    if target == 'claude' and sys.platform.startswith('linux'):
        return 'Claude Desktop installation is disabled on Linux; Claude Code CLI is required'
    arch = platform.machine().lower()
    if arch not in ('x86_64', 'amd64', 'arm64', 'aarch64'):
        return 'unsupported desktop architecture: ' + arch
    if sys.platform == 'darwin':
        return '' if target == 'claude' or arch in ('arm64', 'aarch64') else 'Codex desktop requires Apple Silicon'
    if platforms.is_windows():
        return ''
    if sys.platform.startswith('linux'):
        release = os_release()
        distro, version = release.get('ID'), release.get('VERSION_ID', '')
        supported = ((distro == 'ubuntu' and version in ('24.04', '26.04')) or (distro == 'debian' and version == '13') or
                     (distro == 'fedora' and version in ('43', '44')) or distro == 'arch')
        return '' if supported else 'desktop is not officially supported on this Linux distribution/version'
    return 'desktop is not supported on this operating system'


def command(label: str, args: list, say: Callable[[str], None], quiet: bool = False) -> None:
    """Keep interactive child output intact and show elapsed waiting separately."""
    say(label + ' ...')
    stopped = threading.Event()
    def waiting():
        while not stopped.wait(5):
            say('  Waiting: ' + label)
    worker = threading.Thread(target=waiting, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as output:
            result = platforms.run(args, stdout=output if quiet else None, stderr=subprocess.STDOUT if quiet else None)
            if result.returncode:
                if quiet:
                    output.seek(0)
                    print(output.read(), file=sys.stderr)
                raise ValueError(f'{label} failed (exit {result.returncode}). Review the installer output above and retry.')
    finally:
        stopped.set()
        worker.join()
    say(label + ': complete')


def download(url: str, destination: Path, say: Callable[[str], None]) -> None:
    say('Downloading ' + url + ' ...')
    request = urllib.request.Request(url, headers={'User-Agent': 'agentkit'})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open('wb') as output:
        total = int(response.headers.get('Content-Length') or 0)
        received, last = 0, -1
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            output.write(chunk)
            received += len(chunk)
            current = received // (4 * 1024 * 1024)
            if current != last:
                say(f'  Downloaded {received // 1024} KiB' + (f' / {total // 1024} KiB' if total else ''))
                last = current
    if not received:
        raise ValueError('download returned an empty file: ' + url)
    say('Download complete')


def install(target: str, say: Callable[[str], None], quiet: bool = False) -> None:
    """Call only after separate desktop consent. Never infer success from launch."""
    reason = support(target)
    if reason:
        raise ValueError(reason + '; see ' + PAGES[target])
    arch = 'arm64' if platform.machine().lower() in ('aarch64', 'arm64') else 'x64'
    try:
        with tempfile.TemporaryDirectory(prefix='agentkit-desktop-') as temp:
            directory = Path(temp)
            if sys.platform == 'darwin':
                url = 'https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect' if target == 'claude' else 'https://persistent.oaistatic.com/codex-app-prod/Codex.dmg'
                installer = directory / 'desktop.dmg'
                download(url, installer, say)
                mount = directory / 'mounted'
                mount.mkdir()
                command('Mounting desktop installer', ['hdiutil', 'attach', '-nobrowse', '-mountpoint', str(mount), str(installer)], say, quiet)
                try:
                    bundles = list(mount.glob('*.app'))
                    matching = []
                    for bundle in bundles:
                        info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
                        if info.get('CFBundleIdentifier') == BUNDLE_IDS[target]:
                            matching.append(bundle)
                    if len(matching) != 1:
                        raise ValueError('downloaded disk image has no unique expected application identity; use ' + PAGES[target])
                    bundle = matching[0]
                    command('Verifying desktop signature', ['codesign', '--verify', '--deep', '--strict', str(bundle)], say, quiet)
                    destination = platforms.user_home() / 'Applications' / bundle.name
                    if destination.exists():
                        raise ValueError('refusing to replace existing application: ' + str(destination))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    command('Installing desktop in user Applications', ['ditto', str(bundle), str(destination)], say, quiet)
                finally:
                    command('Unmounting desktop installer', ['hdiutil', 'detach', str(mount)], say, quiet)
            elif platforms.is_windows():
                if target == 'codex':
                    if platforms.find_command('winget'):
                        command('Installing ChatGPT (Codex) from Microsoft Store', ['winget', 'install', '--id', '9PLM9XGG6VKS', '-s', 'msstore'], say, quiet)
                    else:
                        say('Install ChatGPT (Codex) from the official download page: ' + PAGES[target])
                        webbrowser.open(PAGES[target])
                else:
                    installer = directory / 'ClaudeSetup.exe'
                    download(f'https://claude.ai/api/desktop/win32/{arch}/setup/latest/redirect', installer, say)
                    command('Installing Claude desktop', [str(installer)], say, quiet)
            else:
                release = os_release()
                distro = release.get('ID')
                if target == 'codex' and distro in ('ubuntu', 'debian', 'fedora'):
                    ext = 'rpm' if distro == 'fedora' else 'deb'
                    filename = ('chatgpt.' + ('aarch64' if arch == 'arm64' else 'x86_64') + '.rpm') if ext == 'rpm' else 'chatgpt_' + ('arm64' if arch == 'arm64' else 'amd64') + '.deb'
                    installer = directory / filename
                    download(f'https://persistent.oaistatic.com/codex-app-prod/linux/{ext}/latest/{filename}', installer, say)
                    args = ['dnf', 'install', str(installer)] if ext == 'rpm' else ['apt', 'install', str(installer)]
                    if os.geteuid() != 0:
                        args.insert(0, 'sudo')
                    command('Installing ChatGPT (Codex) desktop', args, say, quiet)
                else:
                    # Arch scripts perform a full OS upgrade. Keep these official
                    # steps visible rather than silently changing the system.
                    url = 'https://learn.chatgpt.com/docs/linux/linux-app'
                    say('Complete the official desktop installation: ' + url)
                    if not webbrowser.open(url):
                        say('Open that URL in your browser to continue.')
            if target not in discover():
                answer('Waiting for desktop installation. Finish the installer, then press Enter to verify: ')
            if target not in discover():
                raise ValueError('desktop installation could not be verified. Finish installation and rerun agentkit install.')
            say(target + ' desktop: installed and verified')
    except (OSError, EOFError, subprocess.SubprocessError) as error:
        raise ValueError(f'{target} desktop installation failed: {error}. See {PAGES[target]} and retry.') from error
