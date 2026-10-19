"""Private storage policy over the shared guarded authority I/O layer."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import BinaryIO

from .authority_io import (
    _Directory,
    _parent,
    _windows_close,
    _windows_link,
    _windows_open,
    create_authority_bytes,
    hold_authority_directory,
    normalize_authority_path,
    open_authority_read,
)
from .errors import LifecycleError

_SHARED = {("work",), ("work", "release-2-16"), ("work", "release-2-16", "evidence")}


def private_fingerprint(path: Path, *, held_directories: dict[Path, _Directory] | None = None) -> str:
    """Return actual Windows security metadata after validating its policy."""
    from .windows_security import private_handle_fingerprint

    info = path.lstat()
    with hold_authority_directory(
        path if stat.S_ISDIR(info.st_mode) else path.parent, held_directories=held_directories
    ):
        handle = _windows_open(path, directory=stat.S_ISDIR(info.st_mode), operation="security")
        try:
            return private_handle_fingerprint(handle)
        finally:
            _windows_close(handle)


def private_mode(
    path: Path, info: os.stat_result, modes: tuple[int, ...], *, held_directories: dict[Path, _Directory] | None = None
) -> bool:
    """Inspect real ACLs on Windows; never manufacture POSIX permission bits."""
    if os.name != "nt":
        return stat.S_IMODE(info.st_mode) in modes
    try:
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return False
        if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
            return False
        private_fingerprint(path, held_directories=held_directories)
        if stat.S_ISDIR(info.st_mode):
            return 0o700 in modes
        readonly = bool(getattr(info, "st_file_attributes", 0) & 1)
        return (0o400 if readonly else 0o600) in modes
    except (OSError, LifecycleError):
        return False


def verify_private_ancestors(path: Path, *, root: Path) -> None:
    if not path.is_relative_to(root) or path == root:
        raise LifecycleError("private-storage-unsafe", "Private path is outside its root")
    current = path.parent
    while current != root:
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or (
            current.relative_to(root).parts not in _SHARED and not private_mode(current, info, (0o700,))
        ):
            raise LifecycleError("private-storage-unsafe", "Private ancestor is unsafe")
        current = current.parent


def ensure_private_directory(path: Path, *, boundary: Path) -> None:
    if path == boundary:
        return
    if not path.is_relative_to(boundary):
        raise LifecycleError("private-storage-unsafe", "Private directory is outside its root")
    ensure_private_directory(path.parent, boundary=boundary)
    try:
        if os.name == "nt":
            from .windows_security import create_private_directory

            # Ancestors stay pinned across creation and inspection.
            with hold_authority_directory(path.parent):
                create_private_directory(str(path))
        else:
            path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (
        path.relative_to(boundary).parts not in _SHARED and not private_mode(path, info, (0o700,))
    ):
        raise LifecycleError("private-storage-unsafe", "Existing private directory is unsafe")


def restore_private_readonly(path: Path, before: os.stat_result, raw: bytes, fingerprint: str, *, root: Path) -> None:
    """Restore only a cleared readonly bit on the same private Windows file."""
    if sys.platform != "win32":
        raise LifecycleError("private-storage-unavailable", "Windows readonly restoration is unavailable")
    import ctypes as c
    import msvcrt
    from ctypes import wintypes as w

    from .authority_io import _windows_api, _windows_close
    from .windows_security import private_handle_fingerprint

    class BasicInfo(c.Structure):
        _fields_ = [
            ("creation", c.c_longlong),
            ("access", c.c_longlong),
            ("write", c.c_longlong),
            ("change", c.c_longlong),
            ("attributes", w.DWORD),
        ]

    expected_attributes = before.st_file_attributes
    if not expected_attributes & 1:
        raise LifecycleError("private-storage-unsafe", "Original file was not readonly")
    verify_private_ancestors(path, root=root)
    with hold_authority_directory(path.parent):
        api = _windows_api()
        handle = api.CreateFileW(str(path), 0x80020100, 1, None, 3, 0x00200000, None)
        if handle == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _windows_close(handle)
            raise
        with os.fdopen(fd, "rb") as stream:
            current = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_nlink != 1
                or (current.st_dev, current.st_ino, current.st_size) != (before.st_dev, before.st_ino, before.st_size)
                or current.st_file_attributes & 0x400
                or current.st_file_attributes | 1 != expected_attributes
                or private_handle_fingerprint(handle) != fingerprint
                or stream.read(len(raw) + 1) != raw
            ):
                raise LifecycleError("private-storage-changed", "Readonly restoration target changed")
            # Zero timestamps leave them unchanged. Preserve every original flag.
            basic = BasicInfo(0, 0, 0, 0, expected_attributes)
            api.SetFileInformationByHandle.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD]
            api.SetFileInformationByHandle.restype = w.BOOL
            if not api.SetFileInformationByHandle(handle, 0, c.byref(basic), c.sizeof(basic)):
                raise c.WinError(c.get_last_error())
            final = os.fstat(stream.fileno())
            if final.st_file_attributes != expected_attributes or private_handle_fingerprint(handle) != fingerprint:
                raise LifecycleError("private-storage-changed", "Readonly restoration did not preserve policy")


def _handle_fingerprint(stream: BinaryIO) -> str:
    if sys.platform != "win32":
        raise LifecycleError("private-storage-unavailable", "Windows fingerprint is unavailable")
    import msvcrt

    from .windows_security import private_handle_fingerprint

    return private_handle_fingerprint(msvcrt.get_osfhandle(stream.fileno()))


@contextmanager
def open_private_read(path: Path, *, root: Path, modes: tuple[int, ...] = (0o600,)) -> Iterator[BinaryIO]:
    verify_private_ancestors(path, root=root)
    with open_authority_read(path, root=root) as stream:
        info = os.fstat(stream.fileno())
        if os.name == "nt":
            fingerprint = _handle_fingerprint(stream)
            readonly = bool(getattr(info, "st_file_attributes", 0) & 1)
            safe = (0o400 if readonly else 0o600) in modes
        else:
            fingerprint = ""
            safe = stat.S_IMODE(info.st_mode) in modes
        if not safe:
            raise LifecycleError("private-storage-unsafe", "Private file permissions are unsafe")
        yield stream
        if os.name == "nt" and _handle_fingerprint(stream) != fingerprint:
            raise LifecycleError("private-storage-changed", "Private file access policy changed")
    verify_private_ancestors(path, root=root)


def read_private_bytes(path: Path, *, root: Path, modes: tuple[int, ...] = (0o600,), max_bytes: int = 131072) -> bytes:
    entered = False
    try:
        with open_private_read(path, root=root, modes=modes) as stream:
            entered = True
            before = os.fstat(stream.fileno())
            if before.st_size > max_bytes:
                raise LifecycleError("private-storage-overflow", "Private artifact exceeds its byte limit")
            raw = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > max_bytes:
                raise LifecycleError("private-storage-overflow", "Private artifact exceeds its byte limit")
            fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
            if any(getattr(before, f) != getattr(after, f) for f in fields):
                raise LifecycleError("private-storage-changed", "Private file changed while reading")
    except LifecycleError as exc:
        if exc.code == "authority-input-changed":
            phase = "while reading" if entered else "before reading"
            raise LifecycleError("private-storage-changed", f"Private file changed {phase}") from exc
        raise
    return raw


def create_private_bytes(path: Path, raw: bytes, *, root: Path) -> None:
    ensure_private_directory(path.parent, boundary=root)
    create_authority_bytes(path, raw, root=root, private=True)


class PinnedPrivateDirectory:
    """Windows private operations beneath one held, flushable directory."""

    def __init__(self, directory: _Directory) -> None:
        self.directory = directory
        self.observed: dict[str, tuple[int, int, int, int, str]] = {}

    def stat(self, name: str) -> os.stat_result:
        if normalize_authority_path(name) != name or "/" in name:
            raise LifecycleError("private-storage-unsafe", "A simple private name is required")
        return self.directory.stat_child(name)

    def private_directory(self, path: Path, info: os.stat_result) -> bool:
        return private_mode(path, info, (0o700,), held_directories={self.directory.path: self.directory})

    def _require_write(self) -> None:
        if not self.directory.writable:
            raise LifecycleError("private-storage-unsafe", "Private directory write authority is required")

    def private_file(self, name: str, info: os.stat_result) -> bool:
        from .windows_security import private_handle_fingerprint

        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x401:
            return False
        handle = _windows_open(self.directory.path / name, directory=False, operation="security")
        try:
            private_handle_fingerprint(handle)
            current = self.stat(name)
            return (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino)
        finally:
            _windows_close(handle)

    def read(self, name: str, *, maximum: int, links: int, readonly: bool = False) -> tuple[bytes, dict[str, int]]:
        self.stat(name)
        fd = self.directory.open_child(name)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != links
                or info.st_size > maximum
                or getattr(info, "st_file_attributes", 0) & (0x400 if readonly else 0x401)
            ):
                raise LifecycleError("private-storage-unsafe", "Private file type, links or size is unsafe")
            fingerprint = _handle_fingerprint(stream)
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            current = self.stat(name)
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_nlink")
            if (
                any(getattr(info, f) != getattr(after, f) or getattr(info, f) != getattr(current, f) for f in fields)
                or len(raw) != info.st_size
                or _handle_fingerprint(stream) != fingerprint
            ):
                raise LifecycleError("private-storage-changed", "Private file changed during read")
            self.observed[name] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, fingerprint)
            return raw, {"device": info.st_dev, "inode": info.st_ino}

    def link(self, source: str, destination: str) -> None:
        self._require_write()
        self.stat(source)
        if normalize_authority_path(destination) != destination or "/" in destination:
            raise LifecycleError("private-storage-unsafe", "A simple private name is required")
        expected = self.observed.get(source)
        if expected is None:
            raise LifecycleError("private-storage-unsafe", "Private staging requires a completed read")
        with os.fdopen(self.directory.open_child(source), "rb") as stream:
            info = os.fstat(stream.fileno())
            actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, _handle_fingerprint(stream))
            if actual != expected or info.st_nlink != 1:
                raise LifecycleError("private-storage-changed", "Private staging source identity changed")
            _windows_link(self.directory, stream.fileno(), destination)

    def unlink(self, name: str) -> None:
        """Delete the observed identity through its handle, never a reopened name."""
        if sys.platform != "win32":
            raise LifecycleError("private-storage-unavailable", "Windows pinned deletion is unavailable")
        import ctypes as c
        import msvcrt
        from ctypes import wintypes as w

        self._require_write()
        self.stat(name)
        expected = self.observed.get(name)
        if expected is None:
            raise LifecycleError("private-storage-unsafe", "Private deletion requires a completed read")
        handle = _windows_open(self.directory.path / name, directory=False, operation="delete")
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _windows_close(handle)
            raise
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, _handle_fingerprint(stream))
            if actual != expected or info.st_nlink not in {1, 2}:
                raise LifecycleError("private-storage-changed", "Private deletion identity changed")
            kernel = c.WinDLL("kernel32", use_last_error=True)
            kernel.SetFileInformationByHandle.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD]
            kernel.SetFileInformationByHandle.restype = w.BOOL
            readonly = bool(getattr(info, "st_file_attributes", 0) & 1)
            remove = w.DWORD(0x11) if readonly else c.c_ubyte(1)
            if not kernel.SetFileInformationByHandle(handle, 21 if readonly else 4, c.byref(remove), c.sizeof(remove)):
                raise OSError(c.get_last_error(), "Private handle deletion failed")

    def sync(self) -> None:
        self.directory.sync()


@contextmanager
def private_windows_parent(
    root: Path,
    relative: str,
    *,
    expected_root_identity: tuple[int, int] | None = None,
    writable: bool = False,
    held_parent: PinnedPrivateDirectory | None = None,
) -> Iterator[tuple[PinnedPrivateDirectory, str]]:
    """Hold and recheck every private parent ACL through the selected operation."""
    from .windows_security import private_handle_fingerprint

    name = normalize_authority_path(relative)
    if os.name != "nt":
        raise LifecycleError("private-storage-unavailable", "Windows private operations are unavailable")
    held = {held_parent.directory.path: held_parent.directory} if held_parent is not None else None
    with _parent(root, name, writable=writable, held_directories=held) as (directory, leaf), ExitStack() as stack:
        info = root.lstat()
        if expected_root_identity is not None and (info.st_dev, info.st_ino) != expected_root_identity:
            raise LifecycleError("private-storage-changed", "Private root identity changed")
        fingerprints: list[tuple[int, str]] = []
        current = root
        while True:
            handle = (
                directory.handle
                if current == directory.path
                else _windows_open(current, directory=True, operation="security")
            )
            if handle is None:
                raise LifecycleError("private-storage-unavailable", "Private directory handle is unavailable")
            if current != directory.path:
                stack.callback(_windows_close, handle)
            fingerprints.append((handle, private_handle_fingerprint(handle)))
            if current == directory.path:
                break
            tail = directory.path.relative_to(current).parts
            current = current / tail[0]
        if writable:
            directory.sync()
        yield PinnedPrivateDirectory(directory), leaf
        for handle, fingerprint in fingerprints:
            if private_handle_fingerprint(handle) != fingerprint:
                raise LifecycleError("private-storage-changed", "Private directory policy changed")


def private_tree_paths(root: Path) -> list[Path]:
    """Enumerate a bounded private tree without traversing a reparse point."""
    paths: list[Path] = []

    def visit(directory: Path, depth: int) -> None:
        if depth > 64:
            raise LifecycleError("private-storage-overflow", "Private tree depth exceeds its limit")
        with hold_authority_directory(directory) as held:
            if held.handle is None:
                raise LifecycleError("private-storage-unavailable", "Windows directory handle is unavailable")
            from .windows_security import private_handle_fingerprint

            before = private_handle_fingerprint(held.handle)
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = directory / entry.name
                    normalize_authority_path(path.relative_to(root).as_posix())
                    info = entry.stat(follow_symlinks=False)
                    if len(paths) >= 8192 or getattr(info, "st_file_attributes", 0) & 0x400:
                        raise LifecycleError("private-storage-unsafe", "Private tree entry is unsafe or excessive")
                    if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
                        raise LifecycleError("private-storage-unsafe", "Private tree entry is not regular")
                    paths.append(path)
                    if stat.S_ISDIR(info.st_mode):
                        visit(path, depth + 1)
            if private_handle_fingerprint(held.handle) != before:
                raise LifecycleError("private-storage-changed", "Private tree policy changed during enumeration")

    visit(root, 0)
    return sorted(paths)


def _remove_private_directory(
    path: Path, expected: tuple[int, int], *, root: Path | None = None, root_identity: tuple[int, int] | None = None
) -> None:
    if sys.platform != "win32":
        raise LifecycleError("private-storage-unavailable", "Windows directory deletion is unavailable")
    import ctypes as c
    import msvcrt
    from ctypes import wintypes as w

    from .windows_security import private_handle_fingerprint

    with _parent(path.parent, path.name, writable=True) as (parent, name):
        if root is not None:
            current = root.lstat()
            if (current.st_dev, current.st_ino) != root_identity:
                raise LifecycleError("private-storage-changed", "Private cleanup root changed")
        handle = _windows_open(parent.path / name, directory=True, operation="delete")
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _windows_close(handle)
            raise
        try:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != expected:
                raise LifecycleError("private-storage-changed", "Private directory identity changed")
            private_handle_fingerprint(handle)
            kernel = c.WinDLL("kernel32", use_last_error=True)
            kernel.SetFileInformationByHandle.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD]
            kernel.SetFileInformationByHandle.restype = w.BOOL
            remove = c.c_ubyte(1)
            if not kernel.SetFileInformationByHandle(handle, 4, c.byref(remove), c.sizeof(remove)):
                raise OSError(c.get_last_error(), "Private directory deletion failed")
        finally:
            os.close(fd)
        parent.sync()


def remove_private_tree(root: Path) -> None:
    """Remove a known owned tree; refuse replacements and unknown additions."""
    root_info = root.lstat()
    root_identity = (root_info.st_dev, root_info.st_ino)
    paths = private_tree_paths(root)
    inventory = {path: path.lstat() for path in paths}
    for path in paths:
        info = inventory[path]
        modes = (0o700,) if stat.S_ISDIR(info.st_mode) else (0o400, 0o600)
        if not private_mode(path, info, modes) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise LifecycleError("private-storage-unsafe", "Private cleanup inventory is unsafe")
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        info = inventory[path]
        relative = path.relative_to(root).as_posix()
        if stat.S_ISDIR(info.st_mode):
            _remove_private_directory(path, (info.st_dev, info.st_ino), root=root, root_identity=root_identity)
        else:
            with private_windows_parent(root, relative, expected_root_identity=root_identity, writable=True) as (
                parent,
                name,
            ):
                _raw, identity = parent.read(name, maximum=8388608, links=1, readonly=True)
                if identity != {"device": info.st_dev, "inode": info.st_ino}:
                    raise LifecycleError("private-storage-changed", "Private cleanup file changed")
                parent.unlink(name)
                parent.sync()
    _remove_private_directory(root, root_identity)
