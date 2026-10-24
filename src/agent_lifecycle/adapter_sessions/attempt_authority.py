"""Durable attempt reservation, terminal records and current source checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import read_authority_bytes, sync_authority_directory
from agent_lifecycle.contracts.errors import require_condition as _require

_ROOT = Path("work/release-2-16/evidence/codex-exact-prompt")
_RESERVATION = "attempt-result-reservation.json"
_TERMINAL = "attempt-result-terminal.json"
_PENDING = "attempt-result-terminal.pending.json"
_DISPATCH = "attempt-result-dispatched.json"
_IDENTITY = (
    "runId",
    "taskId",
    "attemptId",
    "operationId",
    "routeId",
    "requestedClaim",
    "planDigest",
    "lockDigest",
    "sourceRevision",
    "requestSha256",
    "finalPromptSha256",
    "commandIdentityHash",
)
_SOURCES = tuple(
    "src/agent_lifecycle/adapter_sessions/" + name
    for name in (
        "bootstrap_r11.py",
        "codex_exact_prompt.py",
        "launch_preflight.py",
        "process.py",
        "process_capture.py",
        "process_control.py",
        "process_groups.py",
        "process_telemetry.py",
        "attempt_authority.py",
        "private_input.py",
        "input_lifecycle.py",
        "codex_input_diagnostics.py",
        "codex_source_exposure.py",
        "codex_source_subject.py",
        "codex_prompt_preparation.py",
        "source_review_contracts.py",
        "source_review_inputs.py",
        "source_review_roles.py",
        "source_review_support.py",
        "source_review_transcript.py",
        "source_review_history.py",
        "source_review_shards.py",
        "source_review_preparation_records.py",
    )
)


def _invocation_namespace(run_id: str, task_id: str, attempt_id: str, operation_id: str | None = None) -> Path:
    """Keep workflow attempts intact; each operation owns a create-only child.

    None selects the original layout for retained legacy artifacts. New prompt
    preparation always supplies its already-bound operationId. Hashing permits
    existing operation identifiers containing separators without path traversal.
    """
    for value in (run_id, task_id, attempt_id):
        _require(
            isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is not None,
            "r11-result-identity",
            "attempt identity is not a path component",
        )
        value = _validated_cast(str, value)
    path = Path(run_id) / task_id / attempt_id
    if operation_id is not None:
        _require(
            isinstance(operation_id, str) and bool(operation_id), "r11-result-identity", "operation identity is missing"
        )
        operation_id = _validated_cast(str, operation_id)
        path = path / "operations" / canonical_digest({"operationId": operation_id})
    return path


def capture_attempt_authority(
    project_root: Path, *, lock_path: Path, manifest_path: Path | None = None
) -> dict[str, Any]:
    """Pin the implementation and lock that will own this attempt's result."""
    root = Path(project_root).absolute()
    lock = Path(lock_path).absolute()
    manifest = Path(manifest_path).absolute() if manifest_path is not None else lock.with_name("plan.manifest.json")
    _require(
        lock.is_relative_to(root) and ".." not in lock.parts, "r11-result-authority", "lock lies outside the project"
    )
    _require(
        manifest.is_relative_to(root) and ".." not in manifest.parts,
        "r11-result-authority",
        "manifest lies outside the project",
    )
    return {
        "lockPath": lock.relative_to(root).as_posix(),
        "manifestPath": manifest.relative_to(root).as_posix(),
        "authoritySourceSha256": {
            name: hashlib.sha256(read_authority_bytes(root / name, root=root, max_bytes=1_048_576)).hexdigest()
            for name in _SOURCES
        },
    }


def _current_authority(root: Path, intent: dict[str, Any]) -> None:
    name = intent.get("lockPath")
    _require(
        isinstance(name, str) and not Path(name).is_absolute() and ".." not in Path(name).parts,
        "r11-result-authority",
        "intent lacks an owned lock path",
    )
    name = _validated_cast(str, name)
    sources = intent.get("authoritySourceSha256")
    _require(
        isinstance(sources, dict) and set(sources) == set(_SOURCES),
        "r11-result-authority",
        "intent lacks complete result-source binding",
    )
    sources = _validated_cast(dict[str, Any], sources)
    manifest_name = intent.get("manifestPath")
    _require(
        isinstance(manifest_name, str)
        and not Path(manifest_name).is_absolute()
        and ".." not in Path(manifest_name).parts,
        "r11-result-authority",
        "intent lacks an owned manifest path",
    )
    manifest_name = _validated_cast(str, manifest_name)
    current = capture_attempt_authority(root, lock_path=root / name, manifest_path=root / manifest_name)
    _require(
        current["authoritySourceSha256"] == sources
        and hashlib.sha256(read_authority_bytes(root / name, root=root, max_bytes=1_048_576)).hexdigest()
        == intent["lockDigest"]
        and canonical_digest(json.loads(read_authority_bytes(root / manifest_name, root=root, max_bytes=1_048_576)))
        == intent["planDigest"],
        "r11-result-authority-stale",
        "result implementation, manifest or lock has changed",
    )


def verify_attempt_reservation(project_root: Path, *, intent_path: Path) -> None:
    """Reopen reserved identity and current authority immediately before start."""
    root = Path(project_root).absolute()
    path = Path(intent_path).absolute()
    _, _, intent = _reservation(root, path)
    _current_authority(root, intent)
    _require(
        not any(
            path.with_name(name).exists() or path.with_name(name).is_symlink()
            for name in (_TERMINAL, _PENDING, _DISPATCH)
        ),
        "r11-result-attempt-reused",
        "attempt already has a result or uncertain publication",
    )


def claim_attempt_start(project_root: Path, *, intent_path: Path) -> None:
    """Consume the reservation once, including concurrent invocations."""
    root = Path(project_root).absolute()
    path = Path(intent_path).absolute()
    verify_attempt_reservation(root, intent_path=path)
    reservation, reserved_raw, _ = _reservation(root, path)
    dispatched = path.with_name(_DISPATCH)
    _write(
        root,
        dispatched,
        {
            "schemaVersion": "alk-r11-attempt-dispatched.v1",
            "status": "START_UNCERTAIN",
            "binding": reservation["binding"],
            "reservationSha256": hashlib.sha256(reserved_raw).hexdigest(),
            "costStatus": "UNAVAILABLE",
        },
    )
    _sync_directory(dispatched.parent)


def record_uncertain_attempt(project_root: Path, *, intent_path: Path) -> None:
    """Keep an explicit sticky hold when launch or publication did not complete."""
    root = Path(project_root).absolute()
    path = Path(intent_path).absolute()
    reservation, _, _ = _reservation(root, path)
    pending = path.with_name(_PENDING)
    if not pending.exists():
        _write(
            root,
            pending,
            {
                "schemaVersion": "alk-r11-attempt-uncertain.v1",
                "status": "START_UNCERTAIN",
                "binding": reservation["binding"],
                "costStatus": "UNAVAILABLE",
                "retryAuthorized": False,
            },
        )
    _sync_directory(pending.parent)


def require_positive_attempt_result(
    project_root: Path, *, intent_path: Path, process_result: dict[str, Any] | None = None
) -> dict[str, Any]:
    root = Path(project_root).absolute()
    path = Path(intent_path).absolute()
    record = read_attempt_result(root, intent_path=path)
    _, _, intent = _reservation(root, path)
    _current_authority(root, intent)
    _require(record["status"] == "PASS", "r11-result-positive-denied", "terminal attempt did not pass")
    if process_result is not None:
        _require(
            record["processResultSha256"] == canonical_digest(process_result),
            "r11-result-positive-join",
            "terminal result belongs to a different process outcome",
        )
    return record


def _read(root: Path, path: Path) -> tuple[dict[str, Any], bytes]:
    # Local imports keep storage usable from the exact-prompt preparation path.
    from agent_lifecycle.adapter_sessions.private_input import _read_private

    raw = _read_private(path, root=root)
    value = json.loads(raw)
    _require(isinstance(value, dict), "r11-result-invalid", "result artifact is not an object")
    value = _validated_cast(dict[str, Any], value)
    return value, raw


def _write(root: Path, path: Path, value: dict[str, Any]) -> None:
    from agent_lifecycle.adapter_sessions.private_input import _write_exclusive

    _write_exclusive(path, canonical_bytes(value), root=root)


def _intent(root: Path, intent_path: Path) -> tuple[dict[str, Any], bytes]:
    path = Path(intent_path).absolute()
    _require(
        path.is_relative_to(root / _ROOT) and path.name == "prelaunch-intent.json",
        "r11-result-identity",
        "intent path is outside the attempt namespace",
    )
    value, raw = _read(root, path)
    _require(
        value.get("schemaVersion") == "alk-codex-prelaunch-intent.v1" and value.get("hostLaunchStarted") is False,
        "r11-result-identity",
        "intent does not describe a prelaunch reservation",
    )
    for key in _IDENTITY:
        _require(isinstance(value.get(key), str) and bool(value[key]), "r11-result-identity", f"intent lacks {key}")
    for key in ("runId", "taskId", "attemptId"):
        _require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value[key]) is not None,
            "r11-result-identity",
            "attempt identity is not a path component",
        )
    legacy = root / _ROOT / _invocation_namespace(value["runId"], value["taskId"], value["attemptId"])
    expected = (
        root / _ROOT / _invocation_namespace(value["runId"], value["taskId"], value["attemptId"], value["operationId"])
    )
    _require(path.parent in (legacy, expected), "r11-result-identity", "intent belongs to a different operation")
    for key in ("planDigest", "lockDigest", "requestSha256", "finalPromptSha256", "commandIdentityHash"):
        _require(
            re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None,
            "r11-result-identity",
            f"{key} is not a SHA-256 digest",
        )
    _require(
        type(value.get("plannedStdinBytes")) is int and value["plannedStdinBytes"] >= 0,
        "r11-result-identity",
        "intent lacks planned input length",
    )
    return value, raw


def reserve_attempt_result(project_root: Path, *, intent_path: Path) -> dict[str, Any]:
    """Durably reserve one identity before the caller can start its child."""
    root = Path(project_root).absolute()
    intent, raw = _intent(root, intent_path)
    record = {
        "schemaVersion": "alk-r11-attempt-reservation.v1",
        "status": "RESERVED",
        "binding": {key: intent[key] for key in _IDENTITY},
        "prelaunchIntentSha256": hashlib.sha256(raw).hexdigest(),
    }
    path = Path(intent_path).absolute().with_name(_RESERVATION)
    _write(root, path, record)
    _sync_directory(path.parent)
    return record


def _reservation(root: Path, intent_path: Path) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    intent, raw = _intent(root, intent_path)
    reservation, reserved_raw = _read(root, intent_path.with_name(_RESERVATION))
    _require(
        reservation.get("schemaVersion") == "alk-r11-attempt-reservation.v1"
        and reservation.get("status") == "RESERVED"
        and reservation.get("prelaunchIntentSha256") == hashlib.sha256(raw).hexdigest()
        and reservation.get("binding") == {key: intent[key] for key in _IDENTITY},
        "r11-result-identity",
        "reservation no longer matches its intent",
    )
    return reservation, reserved_raw, intent


def _positive_receipts(root: Path, directory: Path, intent: dict[str, Any], process_hash: str) -> dict[str, str]:
    start, start_raw = _read(root, directory / "process-start.json")
    delivered, input_raw = _read(root, directory / "process-input.json")
    transport, transport_raw = _read(root, directory / "transport-equivalence.json")
    identity: tuple[str, ...] = ("runId", "taskId", "attemptId", "finalPromptSha256")
    if directory == root / _ROOT / _invocation_namespace(
        intent["runId"], intent["taskId"], intent["attemptId"], intent["operationId"]
    ):
        identity += ("operationId",)
    hashes = {
        "start": hashlib.sha256(start_raw).hexdigest(),
        "input": hashlib.sha256(input_raw).hexdigest(),
        "transport": hashlib.sha256(transport_raw).hexdigest(),
    }
    _require(
        start.get("schemaVersion") == "alk-codex-process-start.v1"
        and delivered.get("schemaVersion") == "alk-codex-process-input.v1"
        and transport.get("schemaVersion") == "alk-codex-os-pipe-transport.v1"
        and start.get("hostLaunchStarted") is True
        and start.get("stdinStatus") == "PENDING"
        and start.get("commandIdentityHash") == intent["commandIdentityHash"]
        and start.get("processIdentityHash") == delivered.get("processIdentityHash") == process_hash
        and all(item.get(key) == intent[key] for item in (start, delivered, transport) for key in identity)
        and delivered.get("status") == "COMPLETE"
        and delivered.get("closeSucceeded") is True
        and delivered.get("acceptedBytes") == intent["plannedStdinBytes"]
        and delivered.get("acceptedSha256") == intent["finalPromptSha256"]
        and transport.get("status") == "OS_PIPE_ACCEPTED"
        and transport.get("processStartSha256") == hashes["start"]
        and transport.get("processInputSha256") == hashes["input"],
        "r11-result-positive-join",
        "positive process result lacks matching observed transport",
    )
    return hashes


def publish_attempt_result(project_root: Path, *, intent_path: Path, process_result: dict[str, Any]) -> dict[str, Any]:
    """Publish once after a proven start; retain a durable pending marker on failure."""
    root = Path(project_root).absolute()
    intent_path = Path(intent_path).absolute()
    reservation, reserved_raw, intent = _reservation(root, intent_path)
    result = process_result
    _require(
        result.get("processStarted") is True and result.get("status") in {"PASS", "FAIL", "BLOCKED"},
        "r11-result-start-unproven",
        "no-start and uncertain-start results need separate reconciliation",
    )
    process_hash = (result.get("startObservation") or {}).get("processIdentityHash")
    _require(
        isinstance(process_hash, str) and re.fullmatch(r"[0-9a-f]{64}", process_hash) is not None,
        "r11-result-start-unproven",
        "started process identity is unavailable",
    )
    process_hash = _validated_cast(str, process_hash)
    _require(
        type(result.get("deadlineMonotonicNs")) is int and result["deadlineMonotonicNs"] > 0,
        "r11-result-deadline-unavailable",
        "original process deadline is unavailable",
    )
    hashes = {}
    if result["status"] == "PASS":
        _require(
            result.get("exitCode") == 0
            and result.get("timedOut") is False
            and result.get("cancelled") is False
            and result.get("cleanup", {}).get("status") == "PASS",
            "r11-result-positive-join",
            "process outcome cannot authorize PASS",
        )
        hashes = _positive_receipts(root, intent_path.parent, intent, process_hash)
    record = {
        "schemaVersion": "alk-r11-attempt-terminal.v1",
        "status": result["status"],
        "binding": reservation["binding"],
        "prelaunchIntentSha256": reservation["prelaunchIntentSha256"],
        "reservationSha256": hashlib.sha256(reserved_raw).hexdigest(),
        "processResultSha256": canonical_digest(result),
        "processIdentityHash": process_hash,
        "deadlineMonotonicNs": result["deadlineMonotonicNs"],
        "receiptSha256": hashes,
        "receiptDisposition": "EXACT_POSITIVE_JOIN" if hashes else "HISTORICAL_ONLY",
        "cleanupStatus": result.get("cleanup", {}).get("status", "UNAVAILABLE"),
        "observerDisposition": result.get("observerDisposition", "UNAVAILABLE"),
        "costStatus": "UNAVAILABLE",
        "retryAuthorized": False,
    }
    record["recordDigest"] = canonical_digest(record)
    terminal = intent_path.with_name(_TERMINAL)
    pending = intent_path.with_name(_PENDING)
    _require(
        not terminal.exists() and not terminal.is_symlink(),
        "r11-result-terminal-conflict",
        "terminal result cannot be overwritten",
    )
    _write(root, pending, record)
    _sync_directory(pending.parent)
    # A complete pending file is fsynced before no-replace publication. Any
    # failure leaves it in place, so even a visible terminal cannot authorize.
    os.link(pending, terminal, follow_symlinks=False)
    _sync_directory(terminal.parent)
    pending.unlink()
    # No durability claim for removing the marker: its reappearance after a
    # crash causes a conservative START_UNCERTAIN refusal, never a false PASS.
    return record


def read_attempt_result(project_root: Path, *, intent_path: Path) -> dict[str, Any]:
    """Validate stored terminal state; late observations cannot resolve failure.

    Callers must separately join the binding to current source, lock, workflow
    and accounting authority. This storage API does not qualify a native run.
    """
    root = Path(project_root).absolute()
    intent_path = Path(intent_path).absolute()
    reservation, reserved_raw, intent = _reservation(root, intent_path)
    pending = intent_path.with_name(_PENDING)
    _require(
        not pending.exists() and not pending.is_symlink(),
        "r11-result-start-uncertain",
        "terminal publication needs reconciliation",
    )
    try:
        record, _ = _read(root, intent_path.with_name(_TERMINAL))
    except (OSError, ValueError, LifecycleError) as exc:
        raise LifecycleError("r11-result-start-uncertain", "terminal result is missing or unreadable") from exc
    _require(
        record.get("schemaVersion") == "alk-r11-attempt-terminal.v1"
        and record.get("status") in {"PASS", "FAIL", "BLOCKED"}
        and record.get("binding") == reservation["binding"]
        and record.get("prelaunchIntentSha256") == reservation["prelaunchIntentSha256"]
        and record.get("reservationSha256") == hashlib.sha256(reserved_raw).hexdigest()
        and record.get("recordDigest") == canonical_digest({k: v for k, v in record.items() if k != "recordDigest"}),
        "r11-result-identity",
        "terminal result does not match the reserved attempt",
    )
    if record["status"] == "PASS":
        _require(
            record["receiptSha256"]
            == _positive_receipts(root, intent_path.parent, intent, record["processIdentityHash"]),
            "r11-result-positive-join",
            "positive observations changed after publication",
        )
    return record


def _sync_directory(path: Path) -> None:
    """Keep the legacy missing-primitive refusal before the shared authority barrier."""
    if os.name != "nt":
        _require(
            hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"),
            "r11-durable-storage-unavailable",
            "directory durability is unavailable on this route",
        )
    sync_authority_directory(path)
