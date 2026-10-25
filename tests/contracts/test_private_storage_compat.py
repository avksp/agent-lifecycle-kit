"""Compatibility consumers retain their existing permissions and refusals."""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from agent_lifecycle.accounting import declared_ledger_legacy
from agent_lifecycle.adapter_sessions import private_input
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts import private_storage_compat as compat
from agent_lifecycle.contracts.private_storage import (
    create_private_bytes,
    ensure_private_directory,
    read_private_bytes,
)

READERS = (private_input._read_private, declared_ledger_legacy._read_private)


class PrivateStorageCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / "private"
        ensure_private_directory(self.parent, boundary=self.root)
        self.path = self.parent / "input"
        create_private_bytes(self.path, b"data", root=self.root)

    def test_both_actual_callers_preserve_bounded_bytes(self) -> None:
        for reader in READERS:
            with self.subTest(reader=reader.__module__):
                self.assertEqual(reader(self.path, root=self.root, max_bytes=4), b"data")
                with self.assertRaises(LifecycleError) as caught:
                    reader(self.path, root=self.root, max_bytes=3)
                self.assertEqual(caught.exception.code, "codex-exact-private-path-unsafe")
                if os.name != "nt":
                    self.assertEqual(caught.exception.message, "private file has unsafe mode, type or size")

    def test_readonly_allowance_keeps_modern_default_strict(self) -> None:
        self.path.chmod(0o400)
        try:
            for reader in READERS:
                with self.subTest(reader=reader.__module__):
                    with self.assertRaises(LifecycleError) as caught:
                        reader(self.path, root=self.root)
                    self.assertEqual(caught.exception.code, "codex-exact-private-path-unsafe")
                    self.assertEqual(reader(self.path, root=self.root, allowed_modes=(0o400,)), b"data")
            with self.assertRaises(LifecycleError):
                read_private_bytes(self.path, root=self.root)
        finally:
            self.path.chmod(0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX shared-parent policy fixture")
    def test_shared_legacy_parents_are_explicit_data(self) -> None:
        parent = self.root
        for name in ("work", "release-2-16", "evidence"):
            parent /= name
            parent.mkdir(mode=0o755)
            parent.chmod(0o755)
        private = parent / "private"
        private.mkdir(mode=0o700)
        path = private / "input"
        path.write_bytes(b"history")
        path.chmod(0o600)
        for reader in READERS:
            self.assertEqual(reader(path, root=self.root), b"history")
        with self.assertRaises(LifecycleError) as caught:
            compat.read_compat_private_bytes(path, root=self.root)
        self.assertEqual(caught.exception.code, "private-storage-unsafe")
        self.assertEqual(caught.exception.message, "private parent is not mode 0700")

    @unittest.skipUnless(os.name == "posix", "POSIX mode and symlink fixture")
    def test_callers_keep_mode_parent_and_symlink_refusals(self) -> None:
        for reader in READERS:
            with self.subTest(reader=reader.__module__):
                self.path.chmod(0o644)
                with self.assertRaises(LifecycleError) as caught:
                    reader(self.path, root=self.root)
                self.assertEqual(caught.exception.code, "codex-exact-private-path-unsafe")
                self.path.chmod(0o600)
                self.parent.chmod(0o755)
                with self.assertRaises(LifecycleError):
                    reader(self.path, root=self.root)
                self.parent.chmod(0o700)
                link = self.parent / "indirect"
                link.symlink_to(self.path)
                try:
                    with self.assertRaises(LifecycleError):
                        reader(link, root=self.root)
                finally:
                    link.unlink()
                with self.assertRaises(LifecycleError) as caught:
                    reader(self.path, root=self.parent / "unrelated")
                self.assertEqual(caught.exception.message, "private artifact lies outside root")

    @unittest.skipUnless(os.name == "posix", "POSIX legacy hardlink compatibility fixture")
    def test_legacy_hardlink_behavior_does_not_relax_modern_reader(self) -> None:
        link = self.parent / "linked"
        os.link(self.path, link)
        for reader in READERS:
            self.assertEqual(reader(link, root=self.root), b"data")
        # Both existing POSIX readers accept stable hardlinks. Preserve that
        # contract rather than inventing a stronger modern-file restriction.
        self.assertEqual(read_private_bytes(link, root=self.root), b"data")

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor-identity fault fixture")
    def test_identity_changes_before_and_after_read_are_refused(self) -> None:
        other = self.parent / "other"
        other.write_bytes(b"data")
        other.chmod(0o600)
        for reader in READERS:
            for observations, phase in (
                ([other.stat()], "before"),
                ([self.path.stat(), other.stat()], "while"),
            ):
                with self.subTest(reader=reader.__module__, phase=phase):
                    with mock.patch.object(compat.os, "fstat", side_effect=observations):
                        with self.assertRaises(LifecycleError) as caught:
                            reader(self.path, root=self.root)
                    self.assertEqual(caught.exception.code, "codex-exact-private-path-unsafe")
                    self.assertEqual(caught.exception.message, f"private file changed {phase} reading")

    @unittest.skipUnless(os.name == "posix", "POSIX bounded-read mutation fixture")
    def test_restored_file_identity_cannot_hide_byte_overflow(self) -> None:
        real_fdopen = os.fdopen
        path = self.path

        @contextmanager
        def changed_read(fd: int, mode: str):
            with real_fdopen(fd, mode) as stream:

                class Reader:
                    def fileno(self) -> int:
                        return stream.fileno()

                    def read(self, limit: int) -> bytes:
                        before = path.stat()
                        path.write_bytes(b"longer")
                        try:
                            return stream.read(limit)
                        finally:
                            path.write_bytes(b"data")
                            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

                yield Reader()

        for reader in READERS:
            with self.subTest(reader=reader.__module__):
                with mock.patch.object(compat.os, "fdopen", side_effect=changed_read):
                    with self.assertRaises(LifecycleError) as caught:
                        reader(path, root=self.root, max_bytes=4)
                self.assertEqual(caught.exception.code, "codex-exact-private-overflow")
                self.assertEqual(path.read_bytes(), b"data")

    def test_windows_delegation_keeps_native_policy_and_legacy_errors(self) -> None:
        target = "agent_lifecycle.contracts.private_storage.read_private_bytes"
        for reader in READERS:
            with self.subTest(reader=reader.__module__):
                with mock.patch(target, return_value=b"native") as native:
                    with mock.patch.object(compat.os, "name", "nt"):
                        value = reader(self.path, root=self.root, allowed_modes=(0o400,), max_bytes=7)
                        self.assertEqual(value, b"native")
                    native.assert_called_once_with(self.path, root=self.root, modes=(0o400,), max_bytes=7)
                failure = LifecycleError("private-storage-overflow", "native refusal")
                with mock.patch(target, side_effect=failure):
                    with mock.patch.object(compat.os, "name", "nt"):
                        with self.assertRaises(LifecycleError) as caught:
                            reader(self.path, root=self.root)
                self.assertEqual(caught.exception.code, "codex-exact-private-path-unsafe")
                self.assertEqual(caught.exception.message, "native refusal")
                self.assertIs(caught.exception.__cause__, failure)
