"""Lazy, handle-bound Windows private storage primitives.

No caller-supplied identity is trusted. Existing permissions are inspected,
never repaired; explicit private descriptors are used only at creation.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, NoReturn

from agent_lifecycle.contracts.errors import LifecycleError


def _apis() -> tuple[Any, Any]:
    if sys.platform != "win32":
        raise LifecycleError("private-storage-unavailable", "Windows security is unavailable")
    import ctypes as c
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    security = c.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.LocalFree.argtypes = [w.HLOCAL]
    kernel.LocalFree.restype = w.HLOCAL
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    security.OpenProcessToken.restype = w.BOOL
    security.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD)]
    security.GetTokenInformation.restype = w.BOOL
    security.ConvertSidToStringSidW.argtypes = [w.LPVOID, c.POINTER(w.LPWSTR)]
    security.ConvertSidToStringSidW.restype = w.BOOL
    security.IsValidSid.argtypes = [w.LPVOID]
    security.IsValidSid.restype = w.BOOL
    security.GetSecurityInfo.argtypes = [
        w.HANDLE,
        c.c_int,
        w.DWORD,
        c.POINTER(w.LPVOID),
        c.POINTER(w.LPVOID),
        c.POINTER(w.LPVOID),
        c.POINTER(w.LPVOID),
        c.POINTER(w.LPVOID),
    ]
    security.GetSecurityInfo.restype = w.DWORD
    security.GetSecurityDescriptorLength.argtypes = [w.LPVOID]
    security.GetSecurityDescriptorLength.restype = w.DWORD
    security.GetAce.argtypes = [w.LPVOID, w.DWORD, c.POINTER(w.LPVOID)]
    security.GetAce.restype = w.BOOL
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        c.POINTER(w.LPVOID),
        c.POINTER(w.DWORD),
    ]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    return kernel, security


def _refuse() -> NoReturn:
    raise LifecycleError("private-storage-unsafe", "Private storage owner or access policy is unsafe")


def duplicate_directory_handle(handle: int) -> int:
    """Duplicate an explicitly held FILE_OBJECT without reopening or adding access."""
    import ctypes as c
    from ctypes import wintypes as w

    kernel, _ = _apis()
    kernel.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE, c.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]
    kernel.DuplicateHandle.restype = w.BOOL
    duplicate = w.HANDLE()
    process = kernel.GetCurrentProcess()
    if not kernel.DuplicateHandle(process, handle, process, c.byref(duplicate), 0, False, 2) or duplicate.value is None:
        raise LifecycleError("private-storage-unavailable", "Held directory duplication failed")
    return duplicate.value


def _sid_text(sid: Any, kernel: Any, security: Any) -> str:
    import ctypes as c
    from ctypes import wintypes as w

    text = w.LPWSTR()
    if not sid or not security.IsValidSid(sid):
        _refuse()
    if not security.ConvertSidToStringSidW(sid, c.byref(text)):
        _refuse()
    try:
        return str(text.value)
    finally:
        kernel.LocalFree(c.cast(text, w.HLOCAL))


def current_user_sid() -> str:
    """Read the process token identity, not an environment variable."""
    import ctypes as c
    from ctypes import wintypes as w

    kernel, security = _apis()
    token = w.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)):
        _refuse()
    try:
        size = w.DWORD()
        security.GetTokenInformation(token, 1, None, 0, c.byref(size))
        if not 0 < size.value <= 65536:
            _refuse()
        buffer = c.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, buffer, size, c.byref(size)):
            _refuse()
        sid = c.cast(buffer, c.POINTER(w.LPVOID)).contents.value
        return _sid_text(sid, kernel, security)
    finally:
        kernel.CloseHandle(token)


def private_handle_fingerprint(handle: int) -> str:
    """Verify actual owner and every ACE; bind the complete descriptor bytes."""
    import ctypes as c
    from ctypes import wintypes as w

    class Acl(c.Structure):
        _fields_ = [
            ("revision", w.BYTE),
            ("reserved", w.BYTE),
            ("size", w.WORD),
            ("count", w.WORD),
            ("reserved2", w.WORD),
        ]

    kernel, security = _apis()
    owner, dacl, descriptor = w.LPVOID(), w.LPVOID(), w.LPVOID()
    result = security.GetSecurityInfo(
        handle,
        1,
        5,
        c.byref(owner),
        None,
        c.byref(dacl),
        None,
        c.byref(descriptor),
    )
    if result or not descriptor:
        _refuse()
    try:
        trusted = {current_user_sid(), "S-1-5-18", "S-1-5-32-544"}
        if _sid_text(owner, kernel, security) not in trusted or not dacl:
            _refuse()
        acl = c.cast(dacl, c.POINTER(Acl)).contents
        if acl.count > 4096 or acl.size < c.sizeof(Acl):
            _refuse()
        for index in range(acl.count):
            ace = w.LPVOID()
            if not security.GetAce(dacl, index, c.byref(ace)) or ace.value is None:
                _refuse()
            header = c.string_at(ace, 4)
            kind, flags = header[0], header[1]
            length = int.from_bytes(header[2:4], "little")
            if kind not in {0, 1} or length < 16 or length > acl.size:
                _refuse()
            # INHERIT_ONLY grants are still relevant to future owned children.
            sid = _sid_text(c.c_void_p(ace.value + 8), kernel, security)
            if kind == 0 and sid not in trusted | {"S-1-3-4"}:
                _refuse()
            if flags & ~0xDF:
                _refuse()
        size = security.GetSecurityDescriptorLength(descriptor)
        if not 0 < size <= 65536:
            _refuse()
        return hashlib.sha256(c.string_at(descriptor, size)).hexdigest()
    finally:
        kernel.LocalFree(descriptor)


@contextmanager
def private_creation_attributes(*, directory: bool) -> Iterator[Any]:
    """Yield SECURITY_ATTRIBUTES with a protected, explicit private DACL."""
    import ctypes as c
    from ctypes import wintypes as w

    class Attributes(c.Structure):
        _fields_ = [
            ("length", w.DWORD),
            ("descriptor", w.LPVOID),
            ("inherit", w.BOOL),
        ]

    kernel, security = _apis()
    sid = current_user_sid()
    flags = "OICI" if directory else ""
    principals = sorted({sid, "SY", "BA"})
    sddl = "O:" + sid + "D:P" + "".join(f"(A;{flags};FA;;;{p})" for p in principals)
    descriptor = w.LPVOID()
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None):
        _refuse()
    try:
        attributes = Attributes(c.sizeof(Attributes), descriptor, False)
        yield c.byref(attributes)
    finally:
        kernel.LocalFree(descriptor)


def create_private_directory(path: str) -> None:
    """Create only; never replace or repair an existing directory."""
    if sys.platform != "win32":
        raise LifecycleError("private-storage-unavailable", "Windows security is unavailable")
    import ctypes as c
    from ctypes import wintypes as w

    kernel, _ = _apis()
    kernel.CreateDirectoryW.argtypes = [w.LPCWSTR, w.LPVOID]
    kernel.CreateDirectoryW.restype = w.BOOL
    with private_creation_attributes(directory=True) as attributes:
        if not kernel.CreateDirectoryW(path, attributes):
            error = c.get_last_error()
            if error == 183:
                raise FileExistsError(path)
            raise OSError(error, "Private directory creation failed")
