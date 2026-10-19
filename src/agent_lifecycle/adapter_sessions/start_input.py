"""Input-summary helpers for the unified start facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.start_receipts import (
    _blocker_summaries,
    _empty_input,
    _planning_input,
    _safe_input,
    _session_input,
    _source_input,
)
from agent_lifecycle.adapter_sessions.task_intake import ADAPTER_TASK_RUN_REQUEST_SCHEMA
from agent_lifecycle.contracts import LifecycleError, load_json_object

__all__ = [
    "_blocker_summaries",
    "_empty_input",
    "_planning_input",
    "_safe_input",
    "_session_input",
    "_source_input",
]


_SESSION_STATE_SCHEMA = "agent-adapter-session-state.v1"

_MANAGED_PROOF_KIND = "alk-managed-adapter-session"

_LINEAGE_STRING_FIELDS = ("runId", "packageId", "planDigest", "sourceRevision", "phase")

_LINEAGE_INTEGER_FIELDS = ("planRevision", "stateRevision")


def _session_blockers(session: dict[str, Any], *, session_id: str, adapter_id: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if session.get("schemaVersion") != _SESSION_STATE_SCHEMA:
        blockers.append({"code": "start-resume-session-schema-invalid"})
    if session.get("sessionId") != session_id:
        blockers.append({"code": "start-resume-session-id-mismatch"})
    if session.get("adapterId") != adapter_id:
        blockers.append({"code": "start-resume-adapter-mismatch"})
    identity = session.get("stateIdentity")
    if identity is None:
        return blockers
    if not isinstance(identity, dict):
        blockers.append({"code": "start-resume-lineage-invalid"})
        return blockers
    missing = [
        field for field in _LINEAGE_STRING_FIELDS if not isinstance(identity.get(field), str) or not identity.get(field)
    ]
    for field in _LINEAGE_INTEGER_FIELDS:
        value = identity.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            missing.append(field)
    if missing:
        blockers.append({"code": "start-resume-lineage-invalid", "fields": sorted(missing)})
        return blockers
    proof = session.get("managedWorkflowProof")
    if not isinstance(proof, dict):
        blockers.append({"code": "start-resume-proof-missing"})
        return blockers
    if (
        proof.get("kind") != _MANAGED_PROOF_KIND
        or proof.get("status") != "PASS"
        or proof.get("adapterId") != adapter_id
        or proof.get("stateIdentity") != identity
    ):
        blockers.append({"code": "start-resume-proof-mismatch"})
    return blockers


def _inspect_task_source(
    *,
    task_file: Path | None,
    task_text: str | None,
    max_input_bytes: int = 32768,
) -> tuple[dict[str, Any], dict[str, Any] | None, bytes]:
    if type(max_input_bytes) is not int or max_input_bytes < 1:
        raise LifecycleError("start-task-input-limit-invalid", "input limit must be a positive integer")
    limit = min(max_input_bytes, 1_048_576)
    if task_text is not None:
        if len(task_text) > limit:
            raise LifecycleError("start-task-input-too-large", "task exceeds the input byte limit")
        data = task_text.encode("utf-8")
        if len(data) > limit:
            raise LifecycleError("start-task-input-too-large", "task exceeds the input byte limit")
        return _source_input("TEXT", "inline-task", data), _parse_payload(data), data
    if task_file is None or not task_file.is_file():
        label = task_file.name if task_file is not None else None
        return {**_empty_input(), "label": label}, None, b""
    try:
        with task_file.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        return {**_empty_input(), "label": task_file.name}, None, b""
    if len(data) > limit:
        raise LifecycleError("start-task-input-too-large", "task exceeds the input byte limit")
    return _source_input("FILE", task_file.name, data), _parse_payload(data), data


def _parse_payload(data: bytes) -> dict[str, Any] | None:
    try:
        return load_json_object(data, label="lifecycle start input")
    except LifecycleError:
        return None


def _is_frozen_input(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schemaVersion") == ADAPTER_TASK_RUN_REQUEST_SCHEMA:
        return True
    return payload.get("schemaVersion") == "agent-plan-manifest.v1" and payload.get("status") == "FROZEN"


__all__ += ["_inspect_task_source", "_is_frozen_input", "_parse_payload", "_session_blockers"]
