"""Incremental, fail-closed Git object inventory and batch reads."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from agent_lifecycle.contracts.performance_limits import DEFAULT_PERFORMANCE_LIMITS

from .errors import NeutralityError
from .policy import NeutralityPolicy


def iter_git_objects(workspace_root: Path, policy: NeutralityPolicy) -> Iterator[tuple[str, bytes]]:
    """Yield exact ``git cat-file -p`` bytes using two long-lived processes."""

    deadline = time.monotonic() + DEFAULT_PERFORMANCE_LIMITS.max_full_scan_wall_seconds
    inventory = _start(
        ["git", "rev-list", "--objects", "--all", "--reflog"],
        cwd=workspace_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
    )
    batch = _start(
        ["git", "cat-file", "--batch"],
        cwd=workspace_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert inventory.stdout is not None and batch.stdin is not None and batch.stdout is not None
    seen: set[str] = set()
    inventory_bytes = 0
    framing_bytes = 0
    expanded_bytes = 0
    try:
        for raw_line in iter(inventory.stdout.readline, b""):
            _check_deadline(deadline)
            inventory_bytes += len(raw_line)
            if inventory_bytes > DEFAULT_PERFORMANCE_LIMITS.max_git_inventory_bytes:
                raise NeutralityError("Git object inventory exceeds the configured byte limit")
            try:
                object_id = raw_line.split(b" ", 1)[0].strip().decode("ascii")
            except UnicodeDecodeError as exc:
                raise NeutralityError("Git object inventory contains an invalid object id") from exc
            if not _valid_object_id(object_id):
                raise NeutralityError("Git object inventory contains an invalid object id")
            if object_id in seen:
                continue
            seen.add(object_id)
            if len(seen) > DEFAULT_PERFORMANCE_LIMITS.max_git_objects:
                raise NeutralityError("Git object inventory exceeds the configured object limit")
            request = (object_id + "\n").encode("ascii")
            framing_bytes += len(request)
            _check_framing(framing_bytes)
            batch.stdin.write(request)
            batch.stdin.flush()
            header = batch.stdout.readline()
            framing_bytes += len(header)
            _check_framing(framing_bytes)
            response_id, object_type, size = _parse_header(header, object_id)
            del response_id
            if size > min(policy.max_object_bytes, DEFAULT_PERFORMANCE_LIMITS.max_git_object_bytes):
                raise NeutralityError("Git object exceeds the configured object byte limit")
            expanded_bytes += size
            if expanded_bytes > DEFAULT_PERFORMANCE_LIMITS.max_git_expanded_bytes:
                raise NeutralityError("Git object expansion exceeds the configured byte limit")
            data = _read_exact(batch.stdout, size)
            delimiter = batch.stdout.read(1)
            framing_bytes += 1
            _check_framing(framing_bytes)
            if delimiter != b"\n":
                raise NeutralityError("Git object batch framing is truncated")
            yield object_id, _pretty_object(data, object_type)
        _check_deadline(deadline)
        if inventory.poll() not in (None, 0):
            raise NeutralityError("Git object inventory command failed")
    except (BrokenPipeError, OSError) as exc:
        raise NeutralityError("Git object batch command failed") from exc
    finally:
        _finish(inventory)
        _finish(batch)


def _pretty_object(data: bytes, object_type: str) -> bytes:
    if object_type != "tree":
        return data
    rows: list[bytes] = []
    offset = 0
    while offset < len(data):
        mode_end = data.find(b" ", offset)
        name_end = data.find(b"\0", mode_end + 1)
        if mode_end <= offset or name_end < 0 or name_end + 21 > len(data):
            raise NeutralityError("Git tree object framing is malformed")
        mode = data[offset:mode_end]
        name = data[mode_end + 1:name_end]
        object_id = data[name_end + 1:name_end + 21].hex().encode("ascii")
        if mode == b"40000":
            display_mode, display_type = b"040000", b"tree"
        elif mode == b"160000":
            display_mode, display_type = mode, b"commit"
        else:
            display_mode, display_type = mode, b"blob"
        rows.append(display_mode + b" " + display_type + b" " + object_id + b"\t" + name + b"\n")
        offset = name_end + 21
    return b"".join(rows)


def _parse_header(header: bytes, expected_id: str) -> tuple[str, str, int]:
    try:
        object_id_bytes, type_bytes, size_bytes = header.rstrip(b"\n").split(b" ", 2)
        object_id = object_id_bytes.decode("ascii")
        object_type = type_bytes.decode("ascii")
        size = int(size_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise NeutralityError("Git object batch header is malformed") from exc
    if object_id != expected_id or object_type not in {"blob", "tree", "commit", "tag"} or size < 0:
        raise NeutralityError("Git object batch header does not match the inventory")
    return object_id, object_type, size


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise NeutralityError("Git object batch data is truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _start(argv: list[str], *, cwd: Path, stdin, stdout):
    try:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise NeutralityError("Git object batch command could not start") from exc


def _finish(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise NeutralityError("Git object scan exceeded its deadline")


def _check_framing(value: int) -> None:
    if value > DEFAULT_PERFORMANCE_LIMITS.max_git_batch_framing_bytes:
        raise NeutralityError("Git object batch framing exceeds the configured byte limit")


def _valid_object_id(value: str) -> bool:
    return len(value) in {40, 64} and all(character in "0123456789abcdef" for character in value)


__all__ = ["iter_git_objects"]
