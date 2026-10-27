"""Binding-cache mocks are UNIT_ONLY; the native last-error case runs on Windows."""

from __future__ import annotations

import ctypes
import os
import stat
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_lifecycle.contracts import LifecycleError, authority_io


def fake_api():
    return SimpleNamespace(
        **{name: Mock() for name in ("CreateFileW", "CloseHandle", "GetFileInformationByHandleEx", "FlushFileBuffers")}
    )


class DirectoryFreshStatTests(unittest.TestCase):
    def test_path_branch_observes_mutation_and_missing_file_freshly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "child"
            child.write_bytes(b"a")
            parent = authority_io._Directory(root, None)
            self.assertEqual(parent.stat_child("child").st_size, 1)
            child.write_bytes(b"changed")
            self.assertEqual(parent.stat_child("child").st_size, 7)
            child.unlink()
            with self.assertRaises(FileNotFoundError) as raised:
                parent.stat_child("child")
            self.assertEqual(raised.exception.filename, str(child))

    def test_path_branch_preserves_symlink_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_bytes(b"value")
            link = root / "link"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"native symlink creation unavailable: {exc}")
            parent = authority_io._Directory(root, None)
            self.assertTrue(stat.S_ISLNK(parent.stat_child("link").st_mode))

    def test_path_branch_preserves_os_error(self):
        parent = authority_io._Directory(Path("unused"), None)
        error = PermissionError(13, "denied", "unchanged")
        with patch.object(authority_io.os, "stat", side_effect=error), self.assertRaises(PermissionError) as raised:
            parent.stat_child("child")
        self.assertIs(raised.exception, error)

    @unittest.skipIf(os.name == "nt", "POSIX directory descriptor contract")
    def test_posix_descriptor_still_selects_held_directory_instead_of_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            held, other = root / "held", root / "other"
            held.mkdir()
            other.mkdir()
            (held / "child").write_bytes(b"held")
            (other / "child").write_bytes(b"different")
            fd = os.open(held, os.O_RDONLY | os.O_DIRECTORY)
            try:
                parent = authority_io._Directory(other, fd)
                with patch.object(authority_io.os, "stat", wraps=os.stat) as observed:
                    self.assertEqual(parent.stat_child("child").st_size, 4)
                observed.assert_called_once_with("child", dir_fd=fd, follow_symlinks=False)
            finally:
                os.close(fd)


class WindowsAuthorityBindingTests(unittest.TestCase):
    def setUp(self):
        authority_io._windows_api_bindings.cache_clear()
        self.addCleanup(authority_io._windows_api_bindings.cache_clear)

    def configured(self, api):
        for name in ("CreateFileW", "CloseHandle", "GetFileInformationByHandleEx", "FlushFileBuffers"):
            self.assertIsInstance(getattr(api, name).argtypes, list)
            self.assertIsNotNone(getattr(api, name).restype)

    def test_cached_bindings_keep_live_opens_metadata_errors_and_closes(self):
        api = fake_api()
        api.CreateFileW.side_effect = [101, 102, ctypes.c_void_p(-1).value]

        def attributes(handle, kind, pointer, size):
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))[0] = 0
            return 1

        api.GetFileInformationByHandleEx.side_effect = attributes
        with (
            patch.object(authority_io.sys, "platform", "win32"),
            patch.object(ctypes, "WinDLL", return_value=api, create=True) as loader,
            patch.object(ctypes, "get_last_error", return_value=2, create=True) as error,
        ):
            first = authority_io._windows_open(Path("first"), directory=False)
            second = authority_io._windows_open(Path("second"), directory=False)
            authority_io._windows_close(first)
            authority_io._windows_close(second)
            with self.assertRaises(FileNotFoundError):
                authority_io._windows_open(Path("missing"), directory=False)
            self.assertIs(authority_io._windows_api(), api)
            self.configured(api)
        loader.assert_called_once_with("kernel32", use_last_error=True)
        self.assertEqual(api.CreateFileW.call_count, 3)
        self.assertEqual(api.GetFileInformationByHandleEx.call_count, 2)
        self.assertEqual(api.CloseHandle.call_args_list[0].args, (101,))
        self.assertEqual(api.CloseHandle.call_args_list[1].args, (102,))
        error.assert_called_once_with()

    def test_platform_refusal_still_runs_after_warming_cache(self):
        with patch.object(ctypes, "WinDLL", return_value=fake_api(), create=True) as loader:
            with patch.object(authority_io.sys, "platform", "win32"):
                authority_io._windows_api()
            with patch.object(authority_io.sys, "platform", "linux"), self.assertRaises(LifecycleError) as raised:
                authority_io._windows_api()
            self.assertEqual(raised.exception.code, "authority-io-unavailable")
            self.assertEqual(loader.call_count, 1)

    def test_failed_initialization_is_not_cached(self):
        api = fake_api()
        with (
            patch.object(authority_io.sys, "platform", "win32"),
            patch.object(ctypes, "WinDLL", side_effect=[OSError("unavailable"), api], create=True) as loader,
        ):
            with self.assertRaises(OSError):
                authority_io._windows_api()
            self.assertIs(authority_io._windows_api(), api)
            self.configured(api)
            self.assertEqual(loader.call_count, 2)

    def test_concurrent_first_calls_publish_only_complete_equivalent_bindings(self):
        barrier = threading.Barrier(2)

        def load(*args, **kwargs):
            api = fake_api()
            barrier.wait(timeout=5)
            return api

        with (
            patch.object(authority_io.sys, "platform", "win32"),
            patch.object(ctypes, "WinDLL", side_effect=load, create=True) as loader,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [pool.submit(authority_io._windows_api) for _ in range(2)]
            values = [future.result(timeout=10) for future in futures]
            for api in values:
                self.configured(api)
            self.assertEqual(values[0].CreateFileW.argtypes, values[1].CreateFileW.argtypes)
            self.assertIn(authority_io._windows_api(), values)
            self.assertEqual(loader.call_count, 2)

    @unittest.skipUnless(sys.platform == "win32", "native Windows thread-local last-error guard")
    def test_native_shared_bindings_preserve_thread_local_errors(self):
        api = authority_io._windows_api()
        barrier = threading.Barrier(2)
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "missing")

            def observe_error(which):
                ctypes.set_last_error(0)
                if which == "missing":
                    handle = api.CreateFileW(missing, 0x80000000, 1, None, 3, 0x00200000, None)
                    self.assertEqual(handle, ctypes.c_void_p(-1).value)
                else:
                    value = (wintypes.DWORD * 2)()
                    self.assertFalse(
                        api.GetFileInformationByHandleEx(None, 9, ctypes.byref(value), ctypes.sizeof(value))
                    )
                barrier.wait(timeout=10)
                return ctypes.get_last_error()

            with ThreadPoolExecutor(max_workers=2) as pool:
                missing_error = pool.submit(observe_error, "missing")
                handle_error = pool.submit(observe_error, "invalid-handle")
                self.assertEqual(missing_error.result(timeout=15), 2)
                self.assertEqual(handle_error.result(timeout=15), 6)
