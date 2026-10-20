"""Create-only artifact authoring over existing canonical and task validators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    read_json_object,
    write_json_create,
)
from agent_lifecycle.contracts.artifact_authoring_schemas import (
    AUTHORING_REQUEST,
    validate_authoring_request,
)
from agent_lifecycle.contracts.canonical import load_json_object, prepare_json_object
from agent_lifecycle.contracts.evidence_receipt_schemas import (
    validate_evidence_receipt_shape,
)
from agent_lifecycle.contracts.redaction import (
    is_sensitive_key,
    redact_text_with_stats,
    redact_value,
)
from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state
from agent_lifecycle.workflow.reviews import (
    task_result_freshness_required,
    validate_task_result,
)


def build_authored_artifact(
    value: dict[str, Any],
    *,
    kind: str,
    redact_advisory: bool = False,
    state: dict[str, Any] | None = None,
    task_id: str | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    request = validate_authoring_request(
        {"schemaVersion": AUTHORING_REQUEST, "kind": kind, "value": value, "redactAdvisory": redact_advisory}
    )
    # Copy through the shared JSON boundary; never mutate caller-owned values.
    result = load_json_object(prepare_json_object(request["value"]))
    if _contains_secret(result) and (
        kind != "json" or not redact_advisory or result.get("authorityClaimed") is not False
    ):
        raise LifecycleError("artifact-sensitive-input", "Sensitive bound input must not be rewritten")
    if kind == "json" and redact_advisory:
        if result.get("authorityClaimed") is not False:
            raise LifecycleError("artifact-sensitive-input", "Redaction requires explicit advisory input")
        result, _changed = redact_value(result)
    if redact_advisory and kind != "json":
        raise LifecycleError("artifact-sensitive-input", "Only explicit advisory JSON may be redacted")
    if kind == "task-result":
        result = _task_result(result, state, task_id, repository_root)
    elif kind == "evidence":
        result = _evidence(result)
    prepare_json_object(result)
    return result


def _contains_secret(value: Any) -> bool:
    """Keep local identity/argv paths; portable exports have a separate boundary."""
    if isinstance(value, dict):
        return any(is_sensitive_key(key) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    if isinstance(value, str):
        return bool(redact_text_with_stats(value)[2]["secretLikeMarkersRedacted"])
    return False


def _bind(value: dict[str, Any], field: str, expected: Any) -> None:
    if field in value and canonical_digest(value[field]) != canonical_digest(expected):
        raise LifecycleError("artifact-lineage-mismatch", "Supplied artifact lineage differs")
    value[field] = expected


def _task_result(
    result: dict[str, Any],
    state: dict[str, Any] | None,
    task_id: str | None,
    root: Path | None,
) -> dict[str, Any]:
    if state is None or not task_id or root is None:
        raise LifecycleError("artifact-state-required", "Task authoring requires state, task and repository root")
    validate_workflow_state(state)
    tasks = [item for item in state["tasks"] if item["id"] == task_id]
    if len(tasks) != 1 or tasks[0].get("status") != "RUNNING":
        raise LifecycleError("artifact-task-not-running", "Task authoring requires the current running task")
    task = tasks[0]
    for field, expected in {
        "schemaVersion": "agent-task-result.v2",
        "runId": state["runId"],
        "taskId": task_id,
        "attempt": task["attempt"],
        "planDigest": state["planDigest"],
        "sourceRevision": state["sourceRevision"],
        "taskPacketHash": task.get("packet", {}).get("sha256"),
    }.items():
        _bind(result, field, expected)
    validate_task_result(
        state,
        task,
        result,
        {"sha256": canonical_digest(result)},
        repository_root=root,
        require_freshness=task_result_freshness_required(state),
        allow_non_accepting_outcome=True,
    )
    return result


def _evidence(result: dict[str, Any]) -> dict[str, Any]:
    producer = result.get("producer")
    if not isinstance(producer, dict) or producer.get("guarantee") != "DECLARED":
        raise LifecycleError("artifact-attestation-unavailable", "Authoring cannot issue attested evidence")
    _bind(result, "payloadDigest", canonical_digest(result.get("payload")))
    _bind(
        result,
        "receiptDigest",
        canonical_digest({key: value for key, value in result.items() if key != "receiptDigest"}),
    )
    return validate_evidence_receipt_shape(result)


def create_artifact(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Store only a fully prepared value; exclusive creation is the final guard."""
    prepare_json_object(value)
    write_json_create(path, value)
    return artifact_summary(path, value)


def artifact_summary(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-artifact-display-summary.v1",
        "status": "PASS",
        "artifact": {"path": str(path), "digest": canonical_digest(value)},
        "authoritative": False,
        "authorityClaimed": False,
        "nativeAcceptanceClaimed": False,
    }


def inspect_artifact(path: Path, *, max_display_bytes: int = 8192) -> dict[str, Any]:
    if type(max_display_bytes) is not int or not 256 <= max_display_bytes <= 65536:
        raise LifecycleError("artifact-display-cap-invalid", "Display cap must be between 256 and 65536 bytes")
    value = read_json_object(path)
    # Inspection must not print credentials that an older external writer stored.
    sanitized, redacted = redact_value(value)
    pretty = json.dumps(sanitized, ensure_ascii=False, indent=2).encode()
    display = pretty[:max_display_bytes].decode("utf-8", errors="ignore")
    return {
        **artifact_summary(path, value),
        "display": display,
        "displayRedacted": redacted,
        "displayTruncated": len(pretty) > max_display_bytes,
        "omittedDisplayBytes": max(0, len(pretty) - len(display.encode())),
    }
