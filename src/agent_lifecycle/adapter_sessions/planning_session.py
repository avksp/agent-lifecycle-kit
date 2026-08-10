"""Ignored, digest-only state for non-executing planning sessions."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.canonical import canonical_bytes

PLANNING_SESSION_SCHEMA = "agent-planning-session-state.v1"
PLANNING_SESSION_ROOT = Path(".alk/planning-sessions")
PLANNING_SESSION_STATES = frozenset(
    {"INTAKE_ACCEPTED", "PLANNING_RUNNING", "REVIEW_REQUIRED", "BLOCKED"}
)
MAX_PLANNING_SESSION_BYTES = 65_536
_SESSION_ID = re.compile(r"^[a-f0-9]{32}$")
_TRANSITIONS = {
    "INTAKE_ACCEPTED": frozenset({"PLANNING_RUNNING", "BLOCKED"}),
    "PLANNING_RUNNING": frozenset({"REVIEW_REQUIRED", "BLOCKED"}),
    "REVIEW_REQUIRED": frozenset(),
    "BLOCKED": frozenset(),
}


def create_planning_session(
    *,
    adapter_id: str,
    requested_mode: str,
    input_summary: dict[str, Any],
    session_root: Path | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create one planning facade state without persisting raw task text."""

    identifier = session_id or uuid.uuid4().hex
    _validate_session_id(identifier)
    safe_input = _safe_input(input_summary)
    lineage = {
        "sessionId": identifier,
        "adapterId": adapter_id,
        "requestedMode": requested_mode,
        "inputDigest": safe_input["sha256"],
    }
    body = {
        "schemaVersion": PLANNING_SESSION_SCHEMA,
        "sessionId": identifier,
        "adapterId": adapter_id,
        "requestedMode": requested_mode,
        "state": "INTAKE_ACCEPTED",
        "sessionRevision": 1,
        "lineageDigest": canonical_digest(lineage),
        "input": safe_input,
        "planningReceiptDigest": None,
        "resultDigest": None,
        "implementationAuthorized": False,
        "rawTaskTextStored": False,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    state = {**body, "stateDigest": canonical_digest(body)}
    path = planning_session_path(identifier, session_root=session_root)
    _prepare_session_directory(path)
    try:
        write_json_create(path, state)
    except FileExistsError as exc:
        raise LifecycleError(
            "planning-session-already-exists",
            "planning session state already exists",
        ) from exc
    return state


def transition_planning_session(
    *,
    session_id: str,
    adapter_id: str,
    expected_state: str,
    new_state: str,
    session_root: Path | None = None,
    planning_receipt: dict[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply one bounded facade transition while preserving session lineage."""

    state = load_planning_session(
        session_id,
        session_root=session_root,
        expected_adapter_id=adapter_id,
    )
    if state["state"] != expected_state:
        raise LifecycleError(
            "planning-session-state-mismatch",
            "planning session is not in the expected state",
            {"expected": expected_state, "actual": state["state"]},
        )
    if new_state not in _TRANSITIONS[expected_state]:
        raise LifecycleError(
            "planning-session-transition-invalid",
            "planning session transition is not allowed",
            {"from": expected_state, "to": new_state},
        )
    body = {key: value for key, value in state.items() if key != "stateDigest"}
    body["state"] = new_state
    body["sessionRevision"] = int(state["sessionRevision"]) + 1
    body["blockers"] = _safe_blockers(blockers or [])
    if planning_receipt is not None:
        receipt_digest = planning_receipt.get("receiptDigest")
        if not isinstance(receipt_digest, str) or len(receipt_digest) != 64:
            raise LifecycleError(
                "planning-session-receipt-invalid",
                "planning receipt is missing its canonical digest",
            )
        body["planningReceiptDigest"] = receipt_digest
        result = planning_receipt.get("result")
        body["resultDigest"] = canonical_digest(result) if isinstance(result, dict) else None
    updated = {**body, "stateDigest": canonical_digest(body)}
    _replace_state(planning_session_path(session_id, session_root=session_root), updated)
    return updated


def load_planning_session(
    session_id: str,
    *,
    session_root: Path | None = None,
    expected_adapter_id: str | None = None,
) -> dict[str, Any]:
    """Load and validate one planning state without attaching a native session."""

    path = planning_session_path(session_id, session_root=session_root)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(_session_root(session_root).resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise LifecycleError("planning-session-missing", "planning session state is unavailable") from exc
    if path.is_symlink() or not resolved.is_file() or resolved.stat().st_size > MAX_PLANNING_SESSION_BYTES:
        raise LifecycleError("planning-session-path-invalid", "planning session state path is invalid")
    state = read_json_object(resolved, label="planning session state")
    _validate_state(state, session_id=session_id, expected_adapter_id=expected_adapter_id)
    return state


def planning_session_exists(session_id: str, *, session_root: Path | None = None) -> bool:
    _validate_session_id(session_id)
    return planning_session_path(session_id, session_root=session_root).is_file()


def planning_session_path(session_id: str, *, session_root: Path | None = None) -> Path:
    _validate_session_id(session_id)
    return _session_root(session_root) / session_id / "state.json"


def _session_root(session_root: Path | None) -> Path:
    return (session_root or PLANNING_SESSION_ROOT).absolute()


def _prepare_session_directory(path: Path) -> None:
    root = path.parent.parent
    if root.is_symlink():
        raise LifecycleError("planning-session-root-symlink", "planning session root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    if path.parent.exists():
        raise LifecycleError("planning-session-already-exists", "planning session directory already exists")
    path.parent.mkdir(mode=0o700)


def _replace_state(path: Path, state: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise LifecycleError("planning-session-path-invalid", "planning session state path is invalid")
    data = canonical_bytes(state) + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        with os.fdopen(os.open(temporary, flags, 0o600), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _validate_state(
    state: dict[str, Any],
    *,
    session_id: str,
    expected_adapter_id: str | None,
) -> None:
    if state.get("schemaVersion") != PLANNING_SESSION_SCHEMA:
        raise LifecycleError("planning-session-schema", "planning session schemaVersion is invalid")
    if state.get("sessionId") != session_id:
        raise LifecycleError("planning-session-lineage-mismatch", "planning session id does not match its path")
    if expected_adapter_id is not None and state.get("adapterId") != expected_adapter_id:
        raise LifecycleError("planning-session-adapter-mismatch", "planning session belongs to another adapter")
    if state.get("state") not in PLANNING_SESSION_STATES:
        raise LifecycleError("planning-session-state-invalid", "planning session state is invalid")
    if state.get("implementationAuthorized") is not False or state.get("rawTaskTextStored") is not False:
        raise LifecycleError("planning-session-authority-invalid", "planning session cannot carry implementation authority")
    if state.get("productionPromotionClaimed") is not False:
        raise LifecycleError("planning-session-production-claim", "planning session cannot claim production promotion")
    body = {key: value for key, value in state.items() if key != "stateDigest"}
    if state.get("stateDigest") != canonical_digest(body):
        raise LifecycleError("planning-session-digest-mismatch", "planning session stateDigest is invalid")
    input_summary = state.get("input")
    if not isinstance(input_summary, dict) or input_summary.get("rawTaskTextStored") is not False:
        raise LifecycleError("planning-session-input-invalid", "planning session input identity is invalid")
    lineage = {
        "sessionId": state.get("sessionId"),
        "adapterId": state.get("adapterId"),
        "requestedMode": state.get("requestedMode"),
        "inputDigest": input_summary.get("sha256"),
    }
    if state.get("lineageDigest") != canonical_digest(lineage):
        raise LifecycleError("planning-session-lineage-mismatch", "planning session lineage digest is invalid")


def _safe_input(value: dict[str, Any]) -> dict[str, Any]:
    digest = value.get("sha256")
    byte_count = value.get("byteCount")
    source = value.get("source")
    if not isinstance(digest, str) or len(digest) != 64:
        raise LifecycleError("planning-session-input-invalid", "planning input digest is invalid")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 1:
        raise LifecycleError("planning-session-input-invalid", "planning input byte count is invalid")
    if not isinstance(source, str) or not source:
        raise LifecycleError("planning-session-input-invalid", "planning input source is invalid")
    return {
        "source": source,
        "sha256": digest,
        "byteCount": byte_count,
        "rawTaskTextStored": False,
    }


def _safe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "code": str(item.get("code") or "planning-session-blocked"),
            **({"message": str(item["message"])} if isinstance(item.get("message"), str) else {}),
        }
        for item in blockers
        if isinstance(item, dict)
    ]


def _validate_session_id(session_id: str) -> None:
    if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
        raise LifecycleError("planning-session-id-invalid", "planning session id is invalid")
