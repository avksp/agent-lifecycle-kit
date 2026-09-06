"""Root-bound regular-file I/O with held directory and file identities."""

from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import Any, BinaryIO

from agent_lifecycle.contracts.errors import LifecycleError

MAX_AUTHORITY_PATH_BYTES = 4096


def normalize_authority_path(name: str, *, label: str = "path") -> str:
    """Validate portable authority path spelling without changing I/O bytes."""

    try:
        return "/".join(_relative_parts(name))
    except LifecycleError as exc:
        raise LifecycleError(exc.code, f"{label}: {exc.message}") from None


def resolve_authority_anchor(base_file: Path, reference: str, *, root: Path | None = None) -> Path:
    """Resolve a relative layout anchor within caller authority, without following links."""

    base = base_file.absolute().parent
    if root is None:
        cwd = Path.cwd()
        root = cwd if base.is_relative_to(cwd) else base
    root = root.absolute()
    if not isinstance(reference, str) or not reference or "\\" in reference or ":" in reference:
        raise LifecycleError("invalid-workflow-state", "packageRoot must be a portable relative anchor")
    if reference != ".":
        parts = reference.split("/")
        first = 0
        while first < len(parts) and parts[first] == "..":
            first += 1
        if first < len(parts):
            _relative_parts("/".join(parts[first:]))
        if len(reference.encode("utf-8")) > MAX_AUTHORITY_PATH_BYTES:
            raise LifecycleError("invalid-workflow-state", "packageRoot exceeds its size limit")
    if not base.is_relative_to(root):
        raise LifecycleError("authority-path-outside-root", "packageRoot escapes the authorized root")
    resolved_parts = list(base.relative_to(root).parts)
    for part in reference.split("/"):
        if part == ".":
            continue
        if part == "..":
            if not resolved_parts:
                raise LifecycleError("authority-path-outside-root", "packageRoot escapes the authorized root")
            resolved_parts.pop()
        else:
            resolved_parts.append(part)
    return root.joinpath(*resolved_parts)


def authority_location(path: Path, *, root: Path | None = None) -> tuple[Path, str]:
    """Bind a caller path; an explicit root is authority, never inferred from a document."""

    candidate = path.absolute()
    if root is None:
        # Only runtime-owned anchors may resolve platform aliases such as macOS /var.
        anchors = (Path.cwd(), Path(tempfile.gettempdir()))
        for anchor in anchors:
            try:
                relative = candidate.relative_to(anchor)
            except ValueError:
                continue
            root = anchor.resolve(strict=True)
            candidate = root / relative
            break
        else:
            root = Path(candidate.anchor)
    root = root.absolute()
    runtime_temp = Path(tempfile.gettempdir())
    try:
        root_tail = root.relative_to(runtime_temp)
        candidate_tail = candidate.relative_to(runtime_temp)
    except ValueError:
        pass
    else:
        root = runtime_temp.resolve(strict=True) / root_tail
        candidate = runtime_temp.resolve(strict=True) / candidate_tail
    try:
        relative_name = candidate.relative_to(root).as_posix()
    except ValueError:
        raise LifecycleError("authority-path-outside-root", "authority path escapes the authorized root") from None
    _relative_parts(relative_name)
    return root, relative_name


def _relative_parts(name: str) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise LifecycleError("invalid-repo-path", "authority path must be portable and relative")
    try:
        if len(name.encode("utf-8")) > MAX_AUTHORITY_PATH_BYTES:
            raise ValueError
    except (UnicodeError, ValueError):
        raise LifecycleError("invalid-repo-path", "authority path exceeds its encoding or size limit") from None
    parts = tuple(name.split("/"))
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((".", " ")):
            raise LifecycleError("invalid-repo-path", "authority path contains an alias or traversal")
        stem = part.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or (
            len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789\u00b9\u00b2\u00b3"
        ):
            raise LifecycleError("invalid-repo-path", "authority path contains a reserved device name")
    return parts


def _require_primitives() -> None:
    if os.name == "nt":
        return
    if not (
        getattr(os, "O_NOFOLLOW", 0)
        and getattr(os, "O_DIRECTORY", 0)
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
    ):
        raise LifecycleError("authority-io-unavailable", "safe authority I/O primitives are unavailable")


def _same_identity(before: os.stat_result, after: os.stat_result, *, content: bool = False) -> None:
    fields: tuple[str, ...] = ("st_dev", "st_ino", "st_mode")
    if content:
        fields += ("st_size", "st_mtime_ns")
        if os.name != "nt":
            fields += ("st_ctime_ns",)
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise LifecycleError("authority-input-changed", "authority input changed during I/O")


def _require_regular(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise LifecycleError("authority-input-not-regular", "authority input must be a non-symlink regular file")


class _Directory:
    def __init__(self, path: Path, fd: int | None, handle: int | None = None) -> None:
        self.path = path
        self.fd = fd
        self.handle = handle

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
        if self.handle is not None:
            _windows_close(self.handle)

    def stat_child(self, name: str) -> os.stat_result:
        if self.fd is not None:
            return os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        return (self.path / name).stat(follow_symlinks=False)

    def open_child(self, name: str) -> int:
        if self.fd is not None:
            return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        return _windows_file(self.path / name)

    def write_child(self, name: str, *, append: bool, mode: int) -> int:
        if self.fd is not None:
            flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            flags |= os.O_APPEND if append else os.O_CREAT | os.O_EXCL
            return os.open(name, flags, mode, dir_fd=self.fd)
        return _windows_file(self.path / name, operation="append" if append else "create")

    def mkdir_child(self, name: str, mode: int) -> None:
        if self.fd is not None:
            os.mkdir(name, mode, dir_fd=self.fd)
        else:
            (self.path / name).mkdir(mode=mode)

    def unlink_child(self, name: str) -> None:
        if self.fd is not None:
            os.unlink(name, dir_fd=self.fd)
        else:
            (self.path / name).unlink()

    def replace_child(self, source: str, destination: str) -> None:
        if self.fd is not None:
            os.replace(source, destination, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        else:
            (self.path / source).replace(self.path / destination)

    def sync(self) -> None:
        if self.fd is not None:
            os.fsync(self.fd)


@contextmanager
def _parent(
    root: Path, relative_name: str, *, create: bool = False, private: bool = False, private_existing: bool = True
) -> Iterator[tuple[_Directory, str]]:
    _require_primitives()
    authority_depth = len(root.parts) - 1
    parts = (*root.parts[1:], *_relative_parts(relative_name))
    root = Path(root.anchor)
    with ExitStack() as stack:
        if os.name == "nt":
            current = _Directory(root, None, _windows_directory(root))
        else:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            current = _Directory(root, fd)
        stack.callback(current.close)
        bindings: list[tuple[_Directory, str, os.stat_result]] = []
        root_info = root.stat(follow_symlinks=False)
        if current.fd is not None:
            _same_identity(root_info, os.fstat(current.fd))
        private_started = False
        for index, part in enumerate(parts[:-1]):
            made = False
            try:
                before = current.stat_child(part)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    current.mkdir_child(part, 0o700 if private else 0o755)
                    made = True
                except FileExistsError:
                    pass
                before = current.stat_child(part)
            if not stat.S_ISDIR(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
                raise LifecycleError("authority-input-symlink", "authority directory must not be a link")
            if current.fd is None:
                child = _Directory(current.path / part, None, _windows_directory(current.path / part))
            else:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current.fd)
                child = _Directory(current.path / part, fd)
            stack.callback(child.close)
            if child.fd is not None:
                _same_identity(before, os.fstat(child.fd))
            private_started |= index >= authority_depth - 1 and (
                part == ".alk" or made or (private_existing and index == len(parts) - 2)
            )
            if private and private_started and child.fd is not None:
                os.fchmod(child.fd, 0o700)
                before = os.fstat(child.fd)
            bindings.append((current, part, before))
            current = child
        _check_bindings(root, root_info, bindings)
        yield current, parts[-1]
        _check_bindings(root, root_info, bindings)


def _check_bindings(root: Path, info: os.stat_result, bindings: list[tuple[_Directory, str, os.stat_result]]) -> None:
    _same_identity(info, root.stat(follow_symlinks=False))
    for parent, name, before in bindings:
        _same_identity(before, parent.stat_child(name))


@contextmanager
def open_authority_read(path: Path, *, root: Path | None = None) -> Iterator[BinaryIO]:
    """Hold a guarded stream; trust results only after successful context exit."""

    root, name = authority_location(path, root=root)
    found = False
    try:
        with _parent(root, name) as (parent, leaf):
            before_path = parent.stat_child(leaf)
            found = True
            _require_regular(before_path)
            fd = parent.open_child(leaf)
            with os.fdopen(fd, "rb") as handle:
                before = os.fstat(handle.fileno())
                _require_regular(before)
                _same_identity(before_path, before, content=True)
                yield handle
                _same_identity(before, os.fstat(handle.fileno()), content=True)
                _same_identity(before, parent.stat_child(leaf), content=True)
    except FileNotFoundError:
        if found:
            raise LifecycleError("authority-input-changed", "authority input changed during I/O") from None
        raise FileNotFoundError(errno.ENOENT, "authority input is unavailable") from None
    except OSError:
        raise LifecycleError("authority-input-unavailable", "authority input cannot be safely read") from None


def read_authority_bytes(path: Path, *, max_bytes: int, root: Path | None = None) -> bytes:
    """Read bounded stable bytes from the actual descriptor consumed by the caller."""

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise LifecycleError("invalid-authority-input-cap", "authority input cap must be positive")
    with open_authority_read(path, root=root) as handle:
        if os.fstat(handle.fileno()).st_size > max_bytes:
            raise LifecycleError("authority-input-too-large", "authority input exceeds its byte limit")
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise LifecycleError("authority-input-too-large", "authority input exceeds its byte limit")
    return data


def ensure_authority_directory(path: Path, *, private: bool = False) -> Path:
    """Create a guarded directory chain; never follow a writable-path symlink."""

    root, name = authority_location(path / ".directory-check")
    try:
        with _parent(root, name, create=True, private=private):
            pass
    except OSError:
        raise LifecycleError(
            "authority-directory-unavailable", "authority directory cannot be safely created"
        ) from None
    return path


def _write_fd(fd: int, data: bytes, *, mode: int | None = None) -> None:
    with os.fdopen(fd, "wb") as handle:
        _require_regular(os.fstat(handle.fileno()))
        if mode is not None and os.name != "nt":
            os.fchmod(handle.fileno(), mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def create_authority_bytes(path: Path, data: bytes, *, root: Path | None = None, private: bool = False) -> bytes:
    """Create only, using the held parent rather than reopening a checked path."""

    root, name = authority_location(path, root=root)
    mode = 0o600 if private else 0o644
    try:
        with _parent(root, name, create=True, private=private) as (parent, leaf):
            with suppress(FileNotFoundError):
                _require_regular(parent.stat_child(leaf))
            fd = parent.write_child(leaf, append=False, mode=mode)
            _write_fd(fd, data, mode=mode if private else None)
            parent.sync()
    except FileExistsError:
        raise FileExistsError(errno.EEXIST, "authority output already exists") from None
    except OSError:
        raise LifecycleError("authority-output-unavailable", "authority output cannot be safely created") from None
    return data


def replace_authority_bytes(path: Path, data: bytes, *, root: Path | None = None) -> bytes:
    """Atomically replace one private regular artifact beneath a held parent."""

    root, name = authority_location(path, root=root)
    temporary = f".authority-{uuid.uuid4().hex}.tmp"
    try:
        with _parent(root, name, create=True, private=True) as (parent, leaf):
            with suppress(FileNotFoundError):
                _require_regular(parent.stat_child(leaf))
            created = False
            try:
                fd = parent.write_child(temporary, append=False, mode=0o600)
                created = True
                _write_fd(fd, data, mode=0o600)
                parent.replace_child(temporary, leaf)
                created = False
                parent.sync()
            finally:
                if created:
                    parent.unlink_child(temporary)
    except OSError:
        raise LifecycleError("authority-output-unavailable", "authority output cannot be safely replaced") from None
    return data


def append_authority_bytes(path: Path, data: bytes, *, root: Path | None = None) -> None:
    """Append to a regular file without following a final or parent alias."""

    root, name = authority_location(path, root=root)
    try:
        with _parent(root, name, create=True, private=True, private_existing=False) as (parent, leaf):
            try:
                before = parent.stat_child(leaf)
            except FileNotFoundError:
                fd = parent.write_child(leaf, append=False, mode=0o600)
            else:
                _require_regular(before)
                fd = parent.write_child(leaf, append=True, mode=0o600)
                try:
                    _same_identity(before, os.fstat(fd), content=True)
                except BaseException:
                    os.close(fd)
                    raise
            _write_fd(fd, data, mode=0o600)
            parent.sync()
    except OSError:
        raise LifecycleError("authority-output-unavailable", "authority journal cannot be safely appended") from None


def _windows_api() -> Any:
    if sys.platform != "win32":
        raise LifecycleError("authority-io-unavailable", "Windows authority I/O is unavailable")
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    api.GetFileInformationByHandleEx.restype = wintypes.BOOL
    return api


def _windows_open(path: Path, *, directory: bool, operation: str = "read") -> int:
    if sys.platform != "win32":
        raise LifecycleError("authority-io-unavailable", "Windows authority I/O is unavailable")
    import ctypes
    from ctypes import wintypes

    api = _windows_api()
    # Omit SHARE_DELETE, but still check identity: some directory renames can succeed.
    access = {"read": 0x80000000, "create": 0x40000000, "append": 0x40000000}[operation]
    handle = api.CreateFileW(
        str(path),
        0 if directory else access,
        3 if directory else 1,
        None,
        1 if operation == "create" else 3,
        0x00200000 | (0x02000000 if directory else 0),
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in {2, 3}:
            raise FileNotFoundError(errno.ENOENT, "authority input is unavailable")
        if error in {80, 183}:
            raise FileExistsError(errno.EEXIST, "authority output already exists")
        raise LifecycleError("authority-input-unavailable", "authority input cannot be safely opened")
    attributes = (wintypes.DWORD * 2)()
    try:
        if not api.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
            raise LifecycleError("authority-io-unavailable", "authority handle attributes are unavailable")
        if attributes[0] & 0x400 or bool(attributes[0] & 0x10) != directory:
            raise LifecycleError("authority-input-symlink", "authority input has an unsafe file type")
    except BaseException:
        api.CloseHandle(handle)
        raise
    return handle


def _windows_directory(path: Path) -> int:
    return _windows_open(path, directory=True)


def _windows_file(path: Path, *, operation: str = "read") -> int:
    if sys.platform != "win32":
        raise LifecycleError("authority-io-unavailable", "Windows authority I/O is unavailable")
    import msvcrt

    handle = _windows_open(path, directory=False, operation=operation)
    try:
        flags = os.O_RDONLY if operation == "read" else os.O_WRONLY
        if operation == "append":
            flags |= os.O_APPEND
        return msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
    except BaseException:
        _windows_close(handle)
        raise


def _windows_close(handle: int) -> None:
    _windows_api().CloseHandle(handle)
