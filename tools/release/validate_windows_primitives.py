"""Create an actual Windows/NTFS integration witness; never qualify a host."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def source_inventory(root: Path) -> list[dict[str, object]]:
    from agent_lifecycle.contracts.authority_io import open_authority_read

    paths = [root / "pyproject.toml", root / "uv.lock"]
    paths += sorted((root / "src/agent_lifecycle").rglob("*.py"))
    paths += [root / "tools/release/validate_windows_primitives.py", root / "tests/windows_test_support.py"]
    if len(paths) > 4096:
        raise ValueError("Source inventory exceeds its file bound")
    rows, total = [], 0
    for path in sorted(paths):
        with open_authority_read(path, root=root) as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > 25_165_824 - total:
                raise ValueError("Source inventory exceeds its byte bound")
            total += size
            raw = stream.read(size + 1)
            if len(raw) != size:
                raise ValueError("Source inventory read changed size")
        rows.append(
            {"path": path.relative_to(root).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    return rows


def actual_filesystem(root: Path) -> str:
    from ctypes import wintypes as w

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetVolumeInformationW.argtypes = [
        w.LPCWSTR,
        w.LPWSTR,
        w.DWORD,
        w.LPVOID,
        w.LPVOID,
        w.LPVOID,
        w.LPWSTR,
        w.DWORD,
    ]
    api.GetVolumeInformationW.restype = w.BOOL
    name = ctypes.create_unicode_buffer(256)
    if not api.GetVolumeInformationW(root.anchor, None, 0, None, None, None, name, len(name)):
        raise ctypes.WinError(ctypes.get_last_error())
    return name.value


def kernel_witnesses() -> list[str]:
    from agent_lifecycle.adapter_sessions.windows_pipe import configure_pipe, read_pipe, write_pipe
    from agent_lifecycle.contracts import LifecycleError
    from agent_lifecycle.contracts.authority_io import open_authority_read, sync_authority_directory
    from agent_lifecycle.contracts.private_storage import (
        create_private_bytes,
        ensure_private_directory,
        read_private_bytes,
        remove_private_tree,
    )

    checks = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        private = root / "private"
        ensure_private_directory(private, boundary=root)
        path, body = private / "raw.bin", "ALK \u00e9 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430".encode()
        create_private_bytes(path, body, root=root)
        if read_private_bytes(path, root=root, max_bytes=len(body)) != body:
            raise ValueError("Private UTF8 roundtrip changed bytes")
        checks.append("actual-private-ACL-create-read-UTF8")
        alias = private / "alias.bin"
        alias.symlink_to(path.name)
        try:
            with open_authority_read(alias, root=root):
                raise ValueError("Authority reader accepted a reparse link")
        except LifecycleError:
            checks.append("actual-reparse-link-refused")
        finally:
            alias.unlink()
        sync_authority_directory(private)
        checks.append("actual-directory-FlushFileBuffers")
        remove_private_tree(private)
        if private.exists():
            raise ValueError("Private removal left the tree behind")
        checks.append("actual-private-handle-delete")
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
        configure_pipe(reader.fileno())
        configure_pipe(writer.fileno())
        try:
            read_pipe(reader.fileno(), 8)
        except BlockingIOError:
            checks.append("actual-live-empty-pipe-is-not-EOF")
        else:
            raise ValueError("Empty live pipe was accepted as EOF")
        if write_pipe(writer.fileno(), b"\xc3\xa9\n") != 3 or read_pipe(reader.fileno(), 8) != b"\xc3\xa9\n":
            raise ValueError("Actual byte pipe changed UTF8 bytes")
        writer.close()
        if read_pipe(reader.fileno(), 8) != b"":
            raise ValueError("Closed writer did not produce EOF")
        checks.append("actual-byte-pipe-UTF8-and-closed-writer-EOF")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    root = args.repository_root.resolve(strict=True)
    evidence = args.evidence if args.evidence.is_absolute() else root / args.evidence
    if evidence.exists():
        parser.error("Evidence already exists; preserve the original attempt")
    sys.path.insert(0, str(root / "src"))
    from agent_lifecycle.contracts import LifecycleError

    started = datetime.now(UTC).isoformat()
    report = {
        "schemaVersion": "alk-actual-windows-primitives.v1",
        "status": "FAIL",
        "startedAtUtc": started,
        "actualArgv": sys.argv,
        "actualCwd": str(Path.cwd()),
        "nativeStarts": 0,
        "wholeHostUsage": None,
        "wholeHostCost": None,
        "hostQualified": False,
        "releaseReady": False,
        "checks": [],
    }
    try:
        if os.name != "nt":
            raise ValueError("Actual Windows is required; a POSIX skip is not a PASS")
        sys.path.insert(0, str(root / "src"))
        from agent_lifecycle.contracts.windows_security import current_user_sid

        report["actualRuntime"] = {
            "osName": os.name,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
            "pythonExecutable": sys.executable,
            "sqlite": sqlite3.sqlite_version,
            "filesystem": actual_filesystem(root),
            "currentTokenSid": current_user_sid(),
        }
        if report["actualRuntime"]["filesystem"] != "NTFS":
            raise ValueError("This witness requires actual NTFS")
        before = source_inventory(root)
        report["sourceBefore"] = before
        report["checks"] = kernel_witnesses()
        report["sourceAfter"] = source_inventory(root)
        report["sourceUnchanged"] = before == report["sourceAfter"]
        if not report["sourceUnchanged"]:
            raise ValueError("Source changed during the actual Windows witness")
        report["status"] = "PASS"
    except (LifecycleError, OSError, ValueError, RuntimeError) as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    report["finishedAtUtc"] = datetime.now(UTC).isoformat()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    with evidence.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(
        json.dumps(
            {"status": report["status"], "evidence": str(evidence), "checks": len(report["checks"]), "nativeStarts": 0}
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
