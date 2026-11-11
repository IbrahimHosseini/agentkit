"""Byte preservation and untrusted manifest boundary tests."""
import hashlib
import json
import os
import stat
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from agentkit_core import managed


class ManagedFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agentkit-managed-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_hash_uses_exact_bytes(self):
        path = self.root / 'data'
        path.write_bytes(b'one\r\ntwo\n')
        self.assertEqual(managed.digest(path), hashlib.sha256(b'one\r\ntwo\n').hexdigest())
        path.write_bytes(b'one\ntwo\n')
        self.assertNotEqual(managed.digest(path), hashlib.sha256(b'one\r\ntwo\n').hexdigest())

    def test_atomic_write_keeps_new_bytes_and_no_temp_files(self):
        path = self.root / 'space فارسی' / 'config.toml'
        managed.atomic_write(path, b'user\r\n')
        self.assertEqual(path.read_bytes(), b'user\r\n')
        managed.atomic_write(path, b'updated\r\n')
        self.assertEqual(path.read_bytes(), b'updated\r\n')
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_atomic_replace_keeps_original_and_cleans_temp(self):
        path = self.root / 'config.toml'
        path.write_bytes(b'original\r\n')
        with mock.patch.object(managed.os, 'replace', side_effect=PermissionError('read-only target')):
            with self.assertRaises(PermissionError):
                managed.atomic_write(path, b'new')
        self.assertEqual(path.read_bytes(), b'original\r\n')
        self.assertEqual(list(self.root.iterdir()), [path])

    @unittest.skipUnless(os.name == 'nt', 'requires native Windows read-only file semantics')
    def test_actual_windows_read_only_target_preserves_original_and_cleans_temp(self):
        path = self.root / 'read-only.toml'
        path.write_bytes(b'original\r\n')
        path.chmod(stat.S_IREAD)
        try:
            with self.assertRaises(PermissionError):
                managed.atomic_write(path, b'new data')
            self.assertEqual(path.read_bytes(), b'original\r\n')
            self.assertEqual(list(self.root.iterdir()), [path])
        finally:
            path.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_load_manifest_keeps_portable_keys(self):
        path = self.root / 'manifest.json'
        data = {'agents/backend.toml': 'a' * 64, 'skills/custom/SKILL.md': 'b' * 64}
        path.write_text(json.dumps({'files': data}), encoding='utf-8')
        self.assertEqual(managed.load_manifest(path), data)

    def test_load_manifest_rejects_escaping_or_foreign_paths(self):
        path = self.root / 'manifest.json'
        for key in ('../outside', '/outside', 'agents/../../outside', 'agents\\outside',
                    'C:/outside', 'agents/C:outside', 'settings.json', ''):
            with self.subTest(key=key):
                path.write_text(json.dumps({'files': {key: 'a' * 64}}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    managed.load_manifest(path)

    def test_load_manifest_rejects_malformed_files(self):
        path = self.root / 'manifest.json'
        for data in ({'files': []}, {'files': {'agents/backend.toml': 12}}):
            with self.subTest(data=data):
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    managed.load_manifest(path)

    def test_manifest_rejects_windows_case_aliases_and_trailing_dots(self):
        path = self.root / 'manifest.json'
        examples = [
            {'agents/backend.toml': 'a', 'agents/Backend.toml': 'b'},
            {'agents/backend.toml.': 'a'},
            {'skills/custom /SKILL.md': 'a'},
        ]
        for files in examples:
            with self.subTest(files=files):
                path.write_text(json.dumps({'files': files}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    managed.load_manifest(path)

    def test_missing_manifest_means_no_managed_files(self):
        self.assertEqual(managed.load_manifest(self.root / 'absent'), {})

    @unittest.skipIf(sys.platform == 'win32', 'symlink privileges are not required on Windows')
    def test_atomic_managed_write_replaces_leaf_link_without_touching_referent(self):
        real = self.root / 'real'
        real.write_bytes(b'original')
        link = self.root / 'link'
        link.symlink_to(real)
        managed.atomic_write(link, b'changed')
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_bytes(), b'changed')
        self.assertEqual(real.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
