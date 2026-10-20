"""Incremental, fail-closed Git object inventory and batch reads."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

from agent_lifecycle.changesets.git_io import BoundedProcess, run_bounded_command
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.performance_limits import DEFAULT_PERFORMANCE_LIMITS

from .errors import NeutralityError
from .policy import NeutralityPolicy


def iter_git_objects(workspace_root: Path, policy: NeutralityPolicy) -> Iterator[tuple[str, bytes]]:
    """Yield Git-native pretty bytes with bounded reads and at most three Git children."""
    limits = DEFAULT_PERFORMANCE_LIMITS
    deadline = time.monotonic() + limits.max_full_scan_wall_seconds
    try:
        quote_paths = _quote_paths(workspace_root, deadline)
        with ExitStack() as stack:
            inventory = stack.enter_context(
                BoundedProcess(
                    ["git", "rev-list", "--objects", "--all", "--reflog"],
                    cwd=workspace_root,
                    deadline=deadline,
                    max_stdout_bytes=limits.max_git_inventory_bytes,
                )
            )
            batch = stack.enter_context(
                BoundedProcess(
                    ["git", "cat-file", "--batch"],
                    cwd=workspace_root,
                    deadline=deadline,
                    max_stdout_bytes=limits.max_git_expanded_bytes + limits.max_git_batch_framing_bytes,
                    writable=True,
                )
            )
            seen: set[str] = set()
            framing_bytes = expanded_bytes = 0
            object_width: int | None = None
            while raw_line := inventory.stdout.readline(min(limits.max_git_inventory_bytes, 1024 * 1024)):
                object_id = _inventory_id(raw_line)
                if object_width is None:
                    object_width = len(object_id) // 2
                if len(object_id) != object_width * 2:
                    raise NeutralityError("Git inventory mixes object formats")
                if object_id in seen:
                    continue
                seen.add(object_id)
                if len(seen) > limits.max_git_objects:
                    raise NeutralityError("Git object inventory exceeds the configured object limit")
                request = (object_id + "\n").encode("ascii")
                framing_bytes += len(request)
                _check_framing(framing_bytes)
                batch.write_request(request)
                header = batch.stdout.readline(256)
                framing_bytes += len(header)
                _check_framing(framing_bytes)
                _response_id, object_type, size = _parse_header(header, object_id)
                if size > min(policy.max_object_bytes, limits.max_git_object_bytes):
                    raise NeutralityError("Git object exceeds the configured object byte limit")
                if expanded_bytes + size > limits.max_git_expanded_bytes:
                    raise NeutralityError("Git object expansion exceeds the configured byte limit")
                data = batch.stdout.read(size)
                if len(data) != size:
                    raise NeutralityError("Git object batch data is truncated")
                delimiter = batch.stdout.read(1)
                framing_bytes += 1
                _check_framing(framing_bytes)
                if delimiter != b"\n":
                    raise NeutralityError("Git object batch framing is truncated")
                pretty = _pretty_object(
                    data,
                    object_type,
                    object_width,
                    quote_paths,
                    min(policy.max_object_bytes, limits.max_git_object_bytes),
                )
                expanded_bytes += max(size, len(pretty))
                if expanded_bytes > limits.max_git_expanded_bytes:
                    raise NeutralityError("Git object expansion exceeds the configured byte limit")
                yield object_id, pretty
            batch.write_request(None)
            if batch.stdout.read(1):
                raise NeutralityError("Git object batch contains unexpected trailing data")
            if inventory.wait() != 0 or batch.wait() != 0:
                raise NeutralityError("Git object command failed")
    except (OSError, LifecycleError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "start-failed"
        raise NeutralityError("Git object transport failed closed: " + code) from exc


def _quote_paths(root: Path, deadline: float) -> bool:
    result = run_bounded_command(
        ["git", "config", "--type=bool", "--get", "core.quotepath"],
        cwd=root,
        timeout_seconds=deadline - time.monotonic(),
        max_stdout_bytes=32,
    )
    if result.returncode == 1 and not result.stdout:
        return True
    value = result.stdout.strip()
    if result.returncode != 0 or value not in (b"true", b"false"):
        raise NeutralityError("Git path quoting configuration is invalid")
    return value == b"true"


def _inventory_id(raw_line: bytes) -> str:
    if not raw_line.endswith(b"\n"):
        raise NeutralityError("Git object inventory framing is truncated")
    try:
        object_id = raw_line.split(b" ", 1)[0].strip().decode("ascii")
    except UnicodeDecodeError as exc:
        raise NeutralityError("Git object inventory contains an invalid object id") from exc
    if not _valid_object_id(object_id):
        raise NeutralityError("Git object inventory contains an invalid object id")
    return object_id


def _pretty_object(
    data: bytes,
    object_type: str,
    object_width: int = 20,
    quote_paths: bool = True,
    max_bytes: int = DEFAULT_PERFORMANCE_LIMITS.max_git_object_bytes,
) -> bytes:
    if object_type != "tree":
        return data
    if object_width not in (20, 32):
        raise NeutralityError("Git object format is unsupported")
    rows: list[bytes] = []
    offset = 0
    total = 0
    while offset < len(data):
        mode_end = data.find(b" ", offset)
        name_end = data.find(b"\0", mode_end + 1)
        entry_end = name_end + 1 + object_width
        if mode_end <= offset or name_end <= mode_end + 1 or entry_end > len(data):
            raise NeutralityError("Git tree object framing is malformed")
        mode = data[offset:mode_end]
        name = data[mode_end + 1 : name_end]
        object_id = data[name_end + 1 : entry_end].hex().encode("ascii")
        if mode in (b"40000", b"040000"):
            display_mode, display_type = b"040000", b"tree"
        elif mode == b"160000":
            display_mode, display_type = mode, b"commit"
        elif mode in (b"100644", b"100755", b"120000"):
            display_mode, display_type = mode, b"blob"
        else:
            raise NeutralityError("Git tree mode is unsupported")
        prefix = display_mode + b" " + display_type + b" " + object_id + b"\t"
        rendered_name = _quote_name(name, quote_paths, max_bytes - total - len(prefix) - 1)
        row = prefix + rendered_name + b"\n"
        total += len(row)
        if total > max_bytes:
            raise NeutralityError("Git rendered object exceeds the configured byte limit")
        rows.append(row)
        offset = entry_end
    return b"".join(rows)


def _quote_name(name: bytes, quote_paths: bool, max_bytes: int) -> bytes:
    escapes = {7: b"\\a", 8: b"\\b", 9: b"\\t", 10: b"\\n", 11: b"\\v", 12: b"\\f", 13: b"\\r", 34: b'\\"', 92: b"\\\\"}
    output = bytearray()
    quoted = False
    for value in name:
        if value in escapes:
            output.extend(escapes[value])
            quoted = True
        elif value < 32 or value == 127 or (quote_paths and value >= 128):
            output.extend(f"\\{value:03o}".encode("ascii"))
            quoted = True
        else:
            output.append(value)
        if len(output) + (2 if quoted else 0) > max_bytes:
            raise NeutralityError("Git rendered object exceeds the configured byte limit")
    return b'"' + bytes(output) + b'"' if quoted else bytes(output)


def _parse_header(header: bytes, expected_id: str) -> tuple[str, str, int]:
    try:
        object_id_bytes, type_bytes, size_bytes = header.rstrip(b"\n").split(b" ", 2)
        object_id = object_id_bytes.decode("ascii")
        object_type = type_bytes.decode("ascii")
        if not header.endswith(b"\n") or not size_bytes.isdigit():
            raise ValueError
        size = int(size_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise NeutralityError("Git object batch header is malformed") from exc
    if object_id != expected_id or object_type not in {"blob", "tree", "commit", "tag"}:
        raise NeutralityError("Git object batch header does not match the inventory")
    return object_id, object_type, size


def _check_framing(value: int) -> None:
    if value > DEFAULT_PERFORMANCE_LIMITS.max_git_batch_framing_bytes:
        raise NeutralityError("Git object batch framing exceeds the configured byte limit")


def _valid_object_id(value: str) -> bool:
    return len(value) in {40, 64} and all(character in "0123456789abcdef" for character in value)


__all__ = ["iter_git_objects"]
