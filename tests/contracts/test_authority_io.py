"""Mutation tests for the descriptor actually consumed by authority readers."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, authority_io


class AuthorityReadTests(unittest.TestCase):
    def test_native_contained_read_and_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "document.json"
            path.write_bytes(b'{"value":1}\n')
            self.assertEqual(authority_io.read_authority_bytes(path, root=root, max_bytes=12), path.read_bytes())
            with self.assertRaises(LifecycleError) as raised:
                authority_io.read_authority_bytes(path, root=root, max_bytes=2)
            self.assertEqual(raised.exception.code, "authority-input-too-large")

    def test_missing_file_is_distinct_from_unsafe_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError) as raised:
                authority_io.read_authority_bytes(Path(directory) / "missing", max_bytes=32)
            self.assertIsNone(raised.exception.filename)

    def test_explicit_root_does_not_grant_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(LifecycleError):
                authority_io.read_authority_bytes(root / ".." / "outside", root=root, max_bytes=32)

    def test_reserved_device_names_are_portably_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name in ("NUL", "aux.txt", "CONIN$", "COM1.json", "LPT9", "file:stream"):
                with self.subTest(name=name), self.assertRaises(LifecycleError):
                    authority_io.read_authority_bytes(Path(directory) / name, max_bytes=32)

    @unittest.skipIf(os.name == "nt", "POSIX rename race; Windows held handles deny this mutation")
    def test_final_replacement_between_stat_and_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "document"
            path.write_bytes(b"original")
            replacement = root / "replacement"
            replacement.write_bytes(b"modified")
            original = authority_io._Directory.open_child

            def swap(parent, name):
                replacement.replace(path)
                return original(parent, name)

            with patch.object(authority_io._Directory, "open_child", swap), self.assertRaises(LifecycleError) as raised:
                authority_io.read_authority_bytes(path, root=root, max_bytes=32)
            self.assertEqual(raised.exception.code, "authority-input-changed")

    @unittest.skipIf(os.name == "nt", "POSIX rename race; Windows held handles deny this mutation")
    def test_parent_swap_cannot_redirect_the_descriptor_to_an_outside_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "inside"
            parent.mkdir()
            (parent / "document").write_bytes(b"inside")
            outside = root / "outside"
            outside.mkdir()
            (outside / "document").write_bytes(b"outside")
            original = authority_io._Directory.open_child
            consumed = []

            def swap(handle, name):
                parent.rename(root / "moved")
                parent.symlink_to(outside, target_is_directory=True)
                fd = original(handle, name)
                consumed.append(os.read(fd, 32))
                os.lseek(fd, 0, os.SEEK_SET)
                return fd

            with patch.object(authority_io._Directory, "open_child", swap), self.assertRaises(LifecycleError):
                authority_io.read_authority_bytes(parent / "document", root=root, max_bytes=32)
            self.assertEqual(consumed, [b"inside"])

    @unittest.skipIf(os.name == "nt", "POSIX concurrent write; Windows reader denies write sharing")
    def test_disappearance_after_read_is_not_reported_as_an_absent_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal"
            path.write_bytes(b"record\n")
            with self.assertRaises(LifecycleError) as raised, authority_io.open_authority_read(path) as handle:
                self.assertEqual(handle.read(), b"record\n")
                path.unlink()
            self.assertEqual(raised.exception.code, "authority-input-changed")

    @unittest.skipIf(os.name == "nt", "POSIX primitive availability contract")
    def test_missing_no_follow_primitive_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document"
            path.write_bytes(b"record")
            with patch.object(os, "O_NOFOLLOW", 0), self.assertRaises(LifecycleError) as raised:
                authority_io.read_authority_bytes(path, max_bytes=32)
            self.assertEqual(raised.exception.code, "authority-io-unavailable")


class AuthorityWriteTests(unittest.TestCase):
    def test_native_create_replace_append_keep_byte_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "private" / "document"
            authority_io.create_authority_bytes(path, b"one\n", root=root, private=True)
            with self.assertRaises(FileExistsError):
                authority_io.create_authority_bytes(path, b"overwrite", root=root)
            self.assertEqual(path.read_bytes(), b"one\n")
            authority_io.replace_authority_bytes(path, b"two\n", root=root)
            authority_io.append_authority_bytes(path, b"three\n", root=root)
            self.assertEqual(path.read_bytes(), b"two\nthree\n")
            self.assertEqual(sorted(item.name for item in path.parent.iterdir()), ["document"])
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixtures; native Windows mutation evidence is separate")
    def test_parent_symlink_never_redirects_create_replace_or_append(self) -> None:
        for operation in (
            authority_io.create_authority_bytes,
            authority_io.replace_authority_bytes,
            authority_io.append_authority_bytes,
        ):
            with self.subTest(operation=operation.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outside = root / "outside"
                outside.mkdir()
                target = outside / "document"
                target.write_bytes(b"unchanged")
                (root / "link").symlink_to(outside, target_is_directory=True)
                with self.assertRaises(LifecycleError):
                    operation(root / "link" / "document", b"must-not-write", root=root)
                self.assertEqual(target.read_bytes(), b"unchanged")

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixtures; native Windows mutation evidence is separate")
    def test_final_symlink_never_mutates_the_target(self) -> None:
        for operation in (
            authority_io.create_authority_bytes,
            authority_io.replace_authority_bytes,
            authority_io.append_authority_bytes,
        ):
            with self.subTest(operation=operation.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "target"
                target.write_bytes(b"unchanged")
                link = root / "link"
                link.symlink_to(target)
                with self.assertRaises((LifecycleError, FileExistsError)):
                    operation(link, b"must-not-write", root=root)
                self.assertEqual(target.read_bytes(), b"unchanged")
                self.assertTrue(link.is_symlink())


if __name__ == "__main__":
    unittest.main()
