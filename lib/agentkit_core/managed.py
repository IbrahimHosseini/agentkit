"""Managed files, byte hashes and safe atomic configuration writes."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path = path.absolute()  # replace a leaf symlink; never write managed data through it
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.agentkit-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        if path.exists():
            shutil.copymode(path, name)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.chmod(name, 0o600)
            os.unlink(name)


def load_manifest(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('invalid manifest object')
    files = data.get('files', {})
    if not isinstance(files, dict):
        raise ValueError('invalid manifest files')
    seen = set()
    for key, value in files.items():
        if not isinstance(key, str):
            raise ValueError('invalid manifest path')
        if key.casefold() in seen:
            raise ValueError('ambiguous manifest paths: ' + key)
        seen.add(key.casefold())
        p = PurePosixPath(key)
        if str(p) != key or any(part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'} for part in p.parts):
            raise ValueError('unsafe manifest path: ' + key)
        if not key or '\\' in key or p.is_absolute() or '..' in p.parts or ':' in key or any(part.endswith((' ', '.')) for part in p.parts) or not key.startswith(('agents/', 'skills/')):
            raise ValueError('unsafe manifest path: ' + key)
        if not isinstance(value, str):
            raise ValueError('invalid manifest hash: ' + key)
    return files


def linked_parent(path: Path, root: Path) -> bool:
    for parent in [path] + list(path.parents)[:len(path.parents)-len(root.parents)]:
        if parent.is_symlink():
            return True
        try:
            if getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400:
                return True  # Windows junction/reparse point
        except FileNotFoundError:
            pass
    return False


def remove_guarded_tree(path: Path) -> None:
    """Remove an already-authorized purge tree, including Windows Git objects.

    Only a read-only regular file may have its writable bit restored, and only
    after rmtree fails to unlink that file. Never retry through a reparse point.
    """
    import stat

    root = path.absolute()

    def retry_read_only_file(function, filename, error_info):
        error = error_info[1]
        child = Path(filename).absolute()
        if (os.name != 'nt' or not isinstance(error, PermissionError)
                or function not in (os.unlink, os.remove)
                or not child.is_relative_to(root)
                or linked_parent(child, root)):
            raise error
        details = child.stat()
        mode = details.st_mode
        if details.st_nlink > 1:
            raise PermissionError('refusing to change attributes of a hard-linked read-only file: ' + str(child)) from error
        if not stat.S_ISREG(mode) or mode & stat.S_IWRITE:
            raise error
        child.chmod(mode | stat.S_IWRITE)
        function(filename)

    shutil.rmtree(root, onerror=retry_read_only_file)
