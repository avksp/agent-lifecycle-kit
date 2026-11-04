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

    def test_windows_open_error_mapping_and_sharing_deadline_are_bounded(self):
        # UNIT_ONLY API/clock observations; production retry bounds are unchanged.
        for error, expected in [(2, FileNotFoundError), (3, FileNotFoundError),
                                (80, FileExistsError), (183, FileExistsError), (5, LifecycleError)]:
            api = fake_api()
            api.CreateFileW.return_value = ctypes.c_void_p(-1).value
            with (
                self.subTest(error=error),
                patch.object(authority_io.sys, "platform", "win32"),
                patch.object(authority_io, "_windows_api", return_value=api),
                patch.object(ctypes, "get_last_error", return_value=error, create=True),
                patch.object(authority_io.time, "sleep") as slept,
            ):
                with self.assertRaises(expected) as raised:
                    authority_io._windows_open(Path("unopened"), directory=False)
                if error == 5:
                    self.assertEqual(raised.exception.code, "authority-input-unavailable")
                    self.assertEqual(raised.exception.details, {"winerror": 5, "operation": "read"})
                self.assertEqual(api.CreateFileW.call_count, 1)
                api.GetFileInformationByHandleEx.assert_not_called()
                api.CloseHandle.assert_not_called()
                slept.assert_not_called()
        api = fake_api()
        api.CreateFileW.return_value = ctypes.c_void_p(-1).value
        with (
            patch.object(authority_io.sys, "platform", "win32"),
            patch.object(authority_io, "_windows_api", return_value=api),
            patch.object(ctypes, "get_last_error", return_value=32, create=True),
            patch.object(authority_io.time, "perf_counter", side_effect=[10.0, 10.01, 10.2]),
            patch.object(authority_io.time, "sleep") as slept,
        ):
            with self.assertRaises(LifecycleError) as raised:
                authority_io._windows_open(Path("contended"), directory=False)
            self.assertEqual(raised.exception.details, {"winerror": 32, "operation": "read"})
            self.assertEqual(api.CreateFileW.call_count, 1)
            slept.assert_called_once_with(0.005)

    def test_windows_metadata_refusal_closes_each_opened_handle_once(self):
        for label, attributes, directory, metadata_ok in [
            ("metadata-unavailable", 0, False, False),
            ("reparse", 0x400, False, True),
            ("directory-as-file", 0x10, False, True),
            ("file-as-directory", 0, True, True),
        ]:
            api = fake_api()
            api.CreateFileW.return_value = 101

            def metadata(handle, kind, pointer, size):
                ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))[0] = attributes
                return int(metadata_ok)

            api.GetFileInformationByHandleEx.side_effect = metadata
            with (
                self.subTest(case=label),
                patch.object(authority_io.sys, "platform", "win32"),
                patch.object(authority_io, "_windows_api", return_value=api),
            ):
                with self.assertRaises(LifecycleError) as raised:
                    authority_io._windows_open(Path("selected"), directory=directory)
                self.assertEqual(
                    raised.exception.code,
                    "authority-io-unavailable" if not metadata_ok else "authority-input-symlink",
                )
                api.CloseHandle.assert_called_once_with(101)

    def test_missing_readonly_foreign_thread_and_durability_capabilities_refuse(self):
        # UNIT_ONLY capability checks with a real directory identity; handles are API doubles.
        api = fake_api()
        with tempfile.TemporaryDirectory() as directory, patch.object(authority_io, "_windows_api", return_value=api):
            root = Path(directory)
            missing = authority_io._Directory(root, None)
            with self.assertRaises(LifecycleError) as raised:
                missing.sync()
            self.assertEqual(raised.exception.code, "authority-io-unavailable")
            held = authority_io._Directory(root, None, handle=101, writable=False)
            try:
                with self.assertRaises(LifecycleError):
                    authority_io._held_windows_directory(root, writable=True, held_directories={root: held})
                with self.assertRaises(LifecycleError):
                    held.sync()
                api.FlushFileBuffers.assert_not_called()

                def foreign_thread():
                    with self.assertRaises(LifecycleError) as raised:
                        authority_io._held_windows_directory(root, writable=False, held_directories={root: held})
                    return raised.exception.code

                with ThreadPoolExecutor(max_workers=1) as pool:
                    self.assertEqual(pool.submit(foreign_thread).result(timeout=5), "authority-io-unavailable")
                held.writable = True
                api.FlushFileBuffers.return_value = 0
                with self.assertRaises(LifecycleError) as raised:
                    held.sync()
                self.assertEqual(raised.exception.code, "authority-durability-unavailable")
            finally:
                held.close()
                held.close()
            api.CloseHandle.assert_called_once_with(101)
