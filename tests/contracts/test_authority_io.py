"""Mutation tests for the descriptor actually consumed by authority readers."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, authority_io


def _set_native_mount_point(path: Path, target: Path) -> None:
    """Exercise a real Windows mount-point FSCTL without replacing its directory."""
    import ctypes
    from ctypes import wintypes

    api = authority_io._windows_api()
    api.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    api.DeviceIoControl.restype = wintypes.BOOL
    handle = api.CreateFileW(str(path), 0x40000000, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        substitute = ("\\??\\" + str(target)).encode("utf-16-le")
        printable = str(target).encode("utf-16-le")
        names = substitute + b"\0\0" + printable + b"\0\0"
        data = (
            struct.pack(
                "<IHHHHHH", 0xA0000003, 8 + len(names), 0, 0, len(substitute), len(substitute) + 2, len(printable)
            )
            + names
        )
        buffer = ctypes.create_string_buffer(data)
        returned = wintypes.DWORD()
        if not api.DeviceIoControl(handle, 0x000900A4, buffer, len(data), None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        api.CloseHandle(handle)


def _filesystem_type(root: Path) -> str:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        api.GetVolumeInformationW.restype = wintypes.BOOL
        name = ctypes.create_unicode_buffer(256)
        if not api.GetVolumeInformationW(root.anchor, None, 0, None, None, None, name, len(name)):
            raise RuntimeError("native filesystem metadata unavailable")
        return name.value
    if sys.platform == "darwin":
        device = (
            subprocess.check_output(["df", "-P", str(root)], text=True, stdin=subprocess.DEVNULL, timeout=10)
            .splitlines()[1]
            .split()[0]
        )
        info = plistlib.loads(
            subprocess.check_output(["diskutil", "info", "-plist", device], stdin=subprocess.DEVNULL, timeout=10)
        )
        return str(info["FilesystemType"])
    return subprocess.check_output(
        ["stat", "-f", "-c", "%T", str(root)], text=True, stdin=subprocess.DEVNULL, timeout=10
    ).strip()


class AuthorityReadTests(unittest.TestCase):
    def test_native_environment_metadata_is_observed_not_acceptance(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        names = (
            "src/agent_lifecycle/contracts/authority_io.py",
            "src/agent_lifecycle/contracts/canonical.py",
            "src/agent_lifecycle/contracts/persistence.py",
            "src/agent_lifecycle/contracts/paths.py",
            "src/agent_lifecycle/workflow/state.py",
            "src/agent_lifecycle/workflow/events.py",
            "src/agent_lifecycle/workflow/artifacts.py",
            "src/agent_lifecycle/workflow/operation_kernel.py",
            "tools/release/validate_repository_input_boundaries.py",
            "tools/release/validate_input_privacy.py",
            "tests/contracts/test_authority_io.py",
            "tests/contracts/test_persistence.py",
            "tests/workflow/test_event_boundaries.py",
            "tests/workflow/test_state_contract.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            filesystem = _filesystem_type(root)
            self.assertTrue(filesystem)
            if os.name == "nt":
                api = authority_io._windows_api()
                primitives = {
                    name: callable(getattr(api, name))
                    for name in ("CreateFileW", "GetFileInformationByHandleEx", "CloseHandle")
                }
            else:
                primitives = {
                    "O_NOFOLLOW": bool(os.O_NOFOLLOW),
                    "O_DIRECTORY": bool(os.O_DIRECTORY),
                    "open_dir_fd": os.open in os.supports_dir_fd,
                    "stat_dir_fd": os.stat in os.supports_dir_fd,
                }
            self.assertTrue(all(primitives.values()))
            payload = {
                "platform": platform.system(),
                "python": platform.python_version(),
                "filesystem": filesystem,
                "primitives": primitives,
                "sourceFiles": {name: hashlib.sha256((repository / name).read_bytes()).hexdigest() for name in names},
                "testId": self.id(),
                "runtimeMetadataOnly": True,
                "acceptanceClaimed": False,
            }
            print("ALK_NATIVE_CONTAINMENT " + json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)

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
            mutation = []

            def swap(handle, name):
                try:
                    parent.rename(root / "moved")
                except PermissionError:
                    if os.name != "nt":
                        raise
                    mutation.append("denied")
                else:
                    mutation.append("substituted")
                    parent.symlink_to(outside, target_is_directory=True)
                fd = original(handle, name)
                if os.name != "nt":
                    consumed.append(os.read(fd, 32))
                    os.lseek(fd, 0, os.SEEK_SET)
                return fd

            yielded = []
            failure = None
            with patch.object(authority_io._Directory, "open_child", swap):
                try:
                    with authority_io.open_authority_read(parent / "document", root=root) as handle:
                        yielded.append(handle.read(32))
                except LifecycleError as exc:
                    failure = exc.code
            if mutation == ["denied"]:
                self.assertEqual(os.name, "nt")
                self.assertIsNone(failure)
                self.assertEqual(yielded, [b"inside"])
                self.assertFalse((root / "moved").exists())
            else:
                self.assertEqual(mutation, ["substituted"])
                self.assertEqual(failure, "authority-input-changed")
                self.assertEqual(yielded, [b"inside"] if os.name != "nt" else [])
                self.assertTrue(parent.is_symlink())
            if os.name != "nt":
                self.assertEqual(consumed, [b"inside"])
            self.assertEqual((outside / "document").read_bytes(), b"outside")

    def test_disappearance_after_read_is_not_reported_as_an_absent_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal"
            path.write_bytes(b"record\n")
            if os.name == "nt":
                with authority_io.open_authority_read(path) as handle:
                    with self.assertRaises(PermissionError):
                        path.unlink()
                    with self.assertRaises(PermissionError):
                        path.write_bytes(b"modified")
                    self.assertEqual(handle.read(), b"record\n")
                self.assertEqual(path.read_bytes(), b"record\n")
            else:
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
    @unittest.skipUnless(os.name == "nt", "Windows FSCTL requires native Windows")
    def test_windows_native_reparse_primitive_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent, outside = root / "parent", root / "outside"
            parent.mkdir()
            outside.mkdir()
            (outside / "marker").write_bytes(b"outside")
            try:
                _set_native_mount_point(parent, outside)
                self.assertTrue(parent.stat(follow_symlinks=False).st_file_attributes & 0x400)
                self.assertEqual((parent / "marker").read_bytes(), b"outside")
            finally:
                if parent.stat(follow_symlinks=False).st_file_attributes & 0x400:
                    parent.rmdir()
            parent.mkdir()
            (parent / "existing").write_bytes(b"inside")
            with self.assertRaises(OSError) as raised:
                _set_native_mount_point(parent, outside)
            self.assertEqual(raised.exception.winerror, 145)
            self.assertFalse(parent.stat(follow_symlinks=False).st_file_attributes & 0x400)
            self.assertEqual((parent / "existing").read_bytes(), b"inside")

    @unittest.skipUnless(os.name == "nt", "Windows FSCTL requires native Windows")
    def test_windows_inplace_reparse_never_redirects_writes(self) -> None:
        for operation in (
            authority_io.create_authority_bytes,
            authority_io.replace_authority_bytes,
            authority_io.append_authority_bytes,
        ):
            with self.subTest(operation=operation.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                parent, outside = root / "parent", root / "outside"
                parent.mkdir()
                outside.mkdir()
                (outside / "marker").write_bytes(b"outside")
                before = {p.name: p.read_bytes() for p in outside.iterdir()}
                original = authority_io._Directory.write_child
                mutation = []

                def substitute(handle, name, *, append, mode):
                    self.assertEqual(mutation, [])
                    self.assertEqual(list(parent.iterdir()), [])
                    try:
                        _set_native_mount_point(parent, outside)
                    except OSError as exc:
                        self.assertIn(exc.winerror, {5, 32})
                        mutation.append({"status": "denied", "winerror": exc.winerror})
                    else:
                        mutation.append({"status": "converted"})
                    return original(handle, name, append=append, mode=mode)

                failure = None
                try:
                    with patch.object(authority_io._Directory, "write_child", substitute):
                        try:
                            operation(parent / "document", b"must-stay-inside", root=root)
                        except LifecycleError as exc:
                            failure = exc.code
                    unchanged = {p.name: p.read_bytes() for p in outside.iterdir()} == before
                    print(
                        "ALK_NATIVE_REPARSE "
                        + json.dumps(
                            {
                                "operation": operation.__name__,
                                "mutation": mutation,
                                "failure": failure,
                                "outsideUnchanged": unchanged,
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    self.assertEqual(len(mutation), 1)
                    self.assertTrue(unchanged, "in-place reparse redirected a write outside the authorized parent")
                    if mutation[0]["status"] == "denied":
                        self.assertIsNone(failure)
                        self.assertEqual((parent / "document").read_bytes(), b"must-stay-inside")
                finally:
                    if parent.stat(follow_symlinks=False).st_file_attributes & 0x400:
                        parent.rmdir()

    def test_native_parent_swap_never_redirects_writes(self) -> None:
        for operation in (
            authority_io.create_authority_bytes,
            authority_io.replace_authority_bytes,
            authority_io.append_authority_bytes,
        ):
            with self.subTest(operation=operation.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent = root / "inside"
                outside = root / "outside"
                parent.mkdir()
                outside.mkdir()
                if operation is not authority_io.create_authority_bytes:
                    (parent / "document").write_bytes(b"inside")
                    (outside / "document").write_bytes(b"outside")
                before = {path.name: path.read_bytes() for path in outside.iterdir()}
                original = authority_io._Directory.write_child
                mutation = []

                def substitute(handle, name, *, append, mode):
                    self.assertEqual(mutation, [])
                    try:
                        parent.rename(root / "moved")
                    except PermissionError:
                        if os.name != "nt":
                            raise
                        mutation.append("denied")
                    else:
                        mutation.append("substituted")
                        parent.symlink_to(outside, target_is_directory=True)
                    return original(handle, name, append=append, mode=mode)

                failure = None
                with patch.object(authority_io._Directory, "write_child", substitute):
                    try:
                        operation(parent / "document", b"must-stay-inside", root=root)
                    except LifecycleError as exc:
                        failure = exc.code
                if mutation == ["denied"]:
                    self.assertEqual(os.name, "nt")
                    self.assertIsNone(failure)
                else:
                    self.assertEqual(mutation, ["substituted"])
                    self.assertIsNotNone(failure)
                self.assertEqual({path.name: path.read_bytes() for path in outside.iterdir()}, before)

    @unittest.skipIf(os.name == "nt", "POSIX directory mode compatibility")
    def test_journal_append_preserves_existing_non_private_parent_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            path = root / "events.jsonl"
            authority_io.append_authority_bytes(path, b"first\n", root=root)
            authority_io.append_authority_bytes(path, b"second\n", root=root)
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_bytes(), b"first\nsecond\n")

    @unittest.skipIf(os.name == "nt", "POSIX permissions; not a Windows ACL claim")
    def test_private_write_does_not_chmod_ancestors_above_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ancestor = Path(directory) / ".alk"
            root = ancestor / "project"
            root.mkdir(parents=True)
            ancestor.chmod(0o755)
            authority_io.create_authority_bytes(root / "private" / "document", b"data", root=root, private=True)
            self.assertEqual(ancestor.stat().st_mode & 0o777, 0o755)
            self.assertEqual((root / "private").stat().st_mode & 0o777, 0o700)

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
