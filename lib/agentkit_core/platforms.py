"""Platform paths and subprocess boundaries."""
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


def is_windows() -> bool:
    return os.name == 'nt'


def user_home() -> Path:
    return Path(os.environ.get('USERPROFILE' if is_windows() else 'HOME') or Path.home())


def find_command(name: str) -> Optional[str]:
    return shutil.which(name)


def command_args(args: List[str]) -> List[str]:
    executable = find_command(args[0]) or args[0]
    if is_windows() and Path(executable).suffix.lower() in ('.cmd', '.bat'):
        if any(any(c in value for c in '&|<>^%!\r\n') for value in [executable] + args[1:]):
            raise ValueError('unsafe cmd launcher argument; use a native executable for these characters')
        # cmd's /s /c has an additional outer quotation layer.
        return [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/s', '/c',
                '"' + subprocess.list2cmdline([executable] + args[1:]) + '"']
    return [executable] + args[1:]


def run(args: List[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command_args(args), **kwargs)


def launcher_bytes(entry: Path) -> bytes:
    """Render an ASCII launcher; encoding the entry avoids batch code-page paths."""
    import base64
    entry = Path(entry).absolute()
    template = (entry.parent.parent / 'bin/agentkit.cmd').read_text(encoding='utf-8')
    encoded = base64.b64encode(str(entry).encode('utf-8')).decode('ascii')
    code = ("import base64,runpy,sys;sys.argv[0]=base64.b64decode('" + encoded +
            "').decode('utf-8');runpy.run_path(sys.argv[0],run_name='__main__')")
    return template.replace('"%~dp0..\\lib\\agentkit.py"', '-c "' + code + '"').encode('ascii')
