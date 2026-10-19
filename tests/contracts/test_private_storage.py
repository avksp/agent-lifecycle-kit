"""Actual private storage policy, kernel denial and cleanup witnesses."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.private_storage import (
    create_private_bytes,
    ensure_private_directory,
    private_fingerprint,
    private_mode,
    private_windows_parent,
    read_private_bytes,
    remove_private_tree,
)


@contextmanager
def unsafe_private_access(path: Path):
    """Temporarily grant real public access, then restore the exact old policy."""
    if os.name != "nt":
        original = stat.S_IMODE(path.lstat().st_mode)
        path.chmod(0o755 if path.is_dir() else 0o644)
        try:
            yield
        finally:
            path.chmod(original)
        return
    import ctypes as c
    from ctypes import wintypes as w

    from agent_lifecycle.contracts.authority_io import _windows_api
    from agent_lifecycle.contracts.windows_security import _apis

    kernel, security = _apis()
    files = _windows_api()
    handle = files.CreateFileW(str(path), 0x00060000, 7, None, 3, 0x02200000, None)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    descriptor = w.LPVOID()
    try:
        error = security.GetSecurityInfo(handle, 1, 4, None, None, None, None, c.byref(descriptor))
        if error:
            raise OSError(error, "Test security snapshot failed")
        original = c.string_at(descriptor, security.GetSecurityDescriptorLength(descriptor))
        kernel.LocalFree(descriptor)
        descriptor = w.LPVOID()
        result = subprocess.run(
            ["icacls", str(path), "/grant", "*S-1-1-0:F"],
            capture_output=True,
            timeout=15,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        try:
            yield
        finally:
            security.SetKernelObjectSecurity.argtypes = [w.HANDLE, w.DWORD, w.LPVOID]
            security.SetKernelObjectSecurity.restype = w.BOOL
            buffer = c.create_string_buffer(original)
            if not security.SetKernelObjectSecurity(handle, 0x80000004, buffer):
                raise c.WinError(c.get_last_error())
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        kernel.CloseHandle(handle)


class PrivateStorageTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Requires actual Windows handle-relative hard links")
    def test_windows_private_staging_uses_held_parent_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            create_private_bytes(root / "raw.bin", b"raw", root=root)
            create_private_bytes(root / "occupied.bin", b"other", root=root)
            with private_windows_parent(root, "raw.bin", writable=True) as (parent, name):
                with self.assertRaises(LifecycleError):
                    parent.link(name, "unread.bin")
                self.assertFalse((root / "unread.bin").exists())
                raw, identity = parent.read(name, maximum=3, links=1)
                with self.assertRaises(OSError):
                    parent.link(name, "occupied.bin")
                self.assertEqual((root / "occupied.bin").read_bytes(), b"other")
                parent.link(name, "staged.bin")
                parent.sync()
                self.assertEqual(parent.read("staged.bin", maximum=3, links=2), (raw, identity))
                parent.unlink(name)
                parent.sync()
                self.assertFalse((root / "raw.bin").exists())
                self.assertEqual(parent.read("staged.bin", maximum=3, links=1), (raw, identity))
                parent.unlink("staged.bin")
                parent.sync()
            self.assertFalse((root / "staged.bin").exists())
            self.assertEqual((root / "occupied.bin").read_bytes(), b"other")

    @unittest.skipUnless(os.name == "nt", "Requires actual Windows directory sharing and DuplicateHandle")
    def test_windows_nested_private_reads_reuse_only_explicit_held_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            create_private_bytes(root / "plan" / "manifest.json", b"{}", root=root)
            for relative in ("raw.bin", "details/raw.bin"):
                create_private_bytes(root / relative, b"raw", root=root)
                with (
                    self.subTest(relative=relative),
                    private_windows_parent(root, relative, writable=True) as (outer, name),
                ):
                    self.assertEqual(outer.read(name, maximum=3, links=1)[0], b"raw")
                    self.assertTrue(outer.private_directory(root, root.lstat()))
                    with private_windows_parent(root, "plan/manifest.json", held_parent=outer) as (reader, leaf):
                        self.assertEqual(reader.read(leaf, maximum=2, links=1)[0], b"{}")
                        with self.assertRaises(LifecycleError):
                            reader.sync()
                    outer.sync()

    @unittest.skipUnless(os.name == "nt", "Requires actual Windows handle lifetime and sharing")
    def test_windows_explicit_duplicate_outlives_original_without_relaxing_sharing(self):
        from agent_lifecycle.contracts.authority_io import hold_authority_directory

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original_context = hold_authority_directory(root, writable=True)
            original = original_context.__enter__()
            duplicate_context = hold_authority_directory(root, writable=True, held_directories={root: original})
            try:
                duplicate = duplicate_context.__enter__()
            except BaseException:
                original_context.__exit__(*sys.exc_info())
                raise
            original_context.__exit__(None, None, None)
            try:
                duplicate.sync()
                self.assertIsNone(original.handle)
                with (
                    self.assertRaises(LifecycleError),
                    hold_authority_directory(root, held_directories={root: original}),
                ):
                    self.fail("Closed directory capability was accepted")
                outcomes = []

                def other_thread():
                    for held in (None, {root: duplicate}):
                        try:
                            with hold_authority_directory(root, writable=True, held_directories=held):
                                outcomes.append("UNEXPECTED_WRITE_OPEN")
                        except LifecycleError:
                            outcomes.append("REFUSED")

                worker = threading.Thread(target=other_thread)
                worker.start()
                worker.join(timeout=10)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcomes, ["REFUSED", "REFUSED"])
                duplicate.sync()
            finally:
                duplicate_context.__exit__(None, None, None)
            with hold_authority_directory(root, writable=True) as fresh:
                fresh.sync()

    @unittest.skipUnless(os.name == "nt", "Requires actual Windows access intent")
    def test_windows_explicit_read_capability_cannot_upgrade_to_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            create_private_bytes(root / "raw.bin", b"raw", root=root)
            with private_windows_parent(root, "raw.bin") as (reader, leaf):
                self.assertEqual(reader.read(leaf, maximum=3, links=1)[0], b"raw")
                for operation in (reader.sync, lambda: reader.link(leaf, "new.bin"), lambda: reader.unlink(leaf)):
                    with self.assertRaises(LifecycleError):
                        operation()
                with (
                    self.assertRaises(LifecycleError),
                    private_windows_parent(root, "raw.bin", writable=True, held_parent=reader),
                ):
                    self.fail("Read capability was upgraded")
            self.assertEqual((root / "raw.bin").read_bytes(), b"raw")
            self.assertFalse((root / "new.bin").exists())

    def test_create_read_and_refuse_unsafe_existing_without_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "private" / "input.bin"
            create_private_bytes(path, b"private-input", root=root)
            self.assertEqual(read_private_bytes(path, root=root), b"private-input")
            self.assertTrue(private_mode(path.parent, path.parent.lstat(), (0o700,)))
            self.assertTrue(private_mode(path, path.lstat(), (0o600,)))
            with self.assertRaises(FileExistsError):
                create_private_bytes(path, b"replacement", root=root)
            for target in (path.parent, path):
                with self.subTest(target=target.name), unsafe_private_access(target):
                    self.assertFalse(private_mode(target, target.lstat(), (0o700,) if target.is_dir() else (0o600,)))
                    with self.assertRaises(LifecycleError):
                        read_private_bytes(path, root=root)
                    if target.is_dir():
                        with self.assertRaises(LifecycleError):
                            ensure_private_directory(target, boundary=root)
                    self.assertFalse(private_mode(target, target.lstat(), (0o700,) if target.is_dir() else (0o600,)))
                self.assertEqual(read_private_bytes(path, root=root), b"private-input")

    def test_private_read_refuses_overflow_and_readonly_policy_is_real(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "private" / "input.bin"
            create_private_bytes(path, b"12345678", root=root)
            with self.assertRaises(LifecycleError):
                read_private_bytes(path, root=root, max_bytes=7)
            path.chmod(0o400)
            try:
                self.assertTrue(private_mode(path, path.lstat(), (0o400,)))
                self.assertEqual(read_private_bytes(path, root=root, modes=(0o400,)), b"12345678")
                with self.assertRaises(LifecycleError):
                    read_private_bytes(path, root=root, modes=(0o600,))
            finally:
                path.chmod(0o600)

    @unittest.skipUnless(os.name == "nt", "Requires actual Windows security descriptors")
    def test_windows_acl_change_invalidates_snapshot_with_unchanged_bytes(self):
        from agent_lifecycle.adapter_sessions.input_lifecycle import _snapshot_digest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            snapshot = root / "snapshot"
            create_private_bytes(snapshot / "config.toml", b"model='fixture'\n", root=root)
            before = _snapshot_digest(snapshot, root=root)
            fingerprint = private_fingerprint(snapshot)
            result = subprocess.run(
                ["icacls", str(snapshot), "/remove:g", "*S-1-5-32-544"],
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotEqual(private_fingerprint(snapshot), fingerprint)
            self.assertNotEqual(_snapshot_digest(snapshot, root=root), before)
            self.assertEqual((snapshot / "config.toml").read_bytes(), b"model='fixture'\n")

    @unittest.skipUnless(os.name == "nt", "Requires actual Windows handle deletion")
    def test_windows_private_tree_cleanup_handles_readonly_and_nested_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            snapshot = root / "snapshot"
            create_private_bytes(snapshot / "nested" / "config.toml", b"private", root=root)
            create_private_bytes(snapshot / "state.json", b"{}", root=root)
            (snapshot / "nested" / "config.toml").chmod(0o400)
            remove_private_tree(snapshot)
            self.assertFalse(snapshot.exists())

    @unittest.skipUnless(os.name == "nt", "Requires actual Windows impersonation in an isolated child")
    def test_windows_private_file_denies_anonymous_kernel_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "private" / "input.bin"
            create_private_bytes(path, b"private", root=root)
            script = """import ctypes as c, sys
from ctypes import wintypes as w
from agent_lifecycle.contracts.authority_io import _windows_api
k = _windows_api()
k.GetCurrentThread.restype = w.HANDLE
a = c.WinDLL('advapi32', use_last_error=True)
a.ImpersonateAnonymousToken.argtypes = [w.HANDLE]
a.ImpersonateAnonymousToken.restype = w.BOOL
a.RevertToSelf.restype = w.BOOL
assert a.ImpersonateAnonymousToken(k.GetCurrentThread())
try:
    h = k.CreateFileW(sys.argv[1], 0x80000000, 7, None, 3, 0x00200000, None)
    error = c.get_last_error()
    if h != c.c_void_p(-1).value:
        k.CloseHandle(h)
        raise AssertionError('anonymous read unexpectedly allowed')
    assert error == 5, error
finally:
    assert a.RevertToSelf()
print('ACTUAL_ANONYMOUS_KERNEL_ACCESS_DENIED_5')
"""
            result = subprocess.run([sys.executable, "-B", "-c", script, str(path)], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(b"ACTUAL_ANONYMOUS_KERNEL_ACCESS_DENIED_5", result.stdout)
