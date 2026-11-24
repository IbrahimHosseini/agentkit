"""Managed files, byte hashes and safe atomic configuration writes."""
import hashlib
import json
import os
import shutil
import stat
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
    data = read_manifest(path)
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


def read_manifest(path: Path) -> dict:
    if linked_parent(path, path.parent.parent):
        raise ValueError('refusing linked manifest: ' + str(path))
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('invalid manifest object')
    return data


def file_state(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, None, None
    if stat.S_ISLNK(info.st_mode):
        return None, None, os.readlink(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('must be a regular file: ' + str(path))
    return path.read_bytes(), stat.S_IMODE(info.st_mode), None


class FileChanges:
    """Stage a target's file changes before publishing its manifest."""

    def __init__(self, backup):
        self.backup = backup
        self.entries = {}

    def set(self, path: Path, data, *, backup=None, expected_hash=None):
        original = file_state(path)
        if expected_hash is not None and (original[0] is None or
                hashlib.sha256(original[0]).hexdigest() != expected_hash):
            raise ValueError('file changed before removal: ' + str(path))
        if path in self.entries:
            raise ValueError('more than one managed file resolves to ' + str(path))
        self.entries[path] = (data, original, backup)

    def commit(self):
        for path, (_, original, backup) in self.entries.items():
            if file_state(path) != original:
                raise ValueError('file changed before installation: ' + str(path))
            if backup:
                self.backup(backup)
        written = []
        try:
            for path, (data, original, _) in self.entries.items():
                if file_state(path) != original:
                    raise ValueError('file changed during installation: ' + str(path))
                written.append((path, original))
                if data is None or original[2] is not None:
                    path.unlink(missing_ok=True)
                if data is not None:
                    atomic_write(path, data)
        except (Exception, KeyboardInterrupt):
            failed = []
            for path, original in reversed(written):
                try:
                    if file_state(path) == original:
                        continue
                    data, mode, link = original
                    if data is None:
                        path.unlink(missing_ok=True)
                        if link is not None:
                            path.symlink_to(link)
                    else:
                        atomic_write(path, data)
                        path.chmod(mode)
                except (OSError, ValueError):
                    failed.append(str(path))
            if failed:
                raise ValueError('installation recovery incomplete for ' + ', '.join(failed)
                                 + '; see agentkit/backups') from None
            raise


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
