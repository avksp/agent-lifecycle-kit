"""Schemas for bounded, projection-first workflow continuation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.schema_builders import open_object_schema

MAX_CONTINUATION_BATCH_STEPS = 128
CONTINUATION_BATCH_STOP_REASONS = (
    "TERMINAL",
    "INPUT_REQUIRED",
    "WAITING",
    "BLOCKED",
    "AUDIT_REQUIRED",
    "HUMAN_DECISION_REQUIRED",
    "BUDGET_DECISION_REQUIRED",
    "EXTERNAL_ACTION_REQUIRED",
    "PLAN_AUTHORITY_REQUIRED",
    "CAP_TRANSITIONS",
    "CAP_BYTES",
    "STALE_BUNDLE_ENTRY",
    "RETRY_PROOF_REQUIRED",
    "RETRY_PROOF_MISMATCH",
)

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 64}
_REQUIRED_INPUTS = {"type": "array", "items": {"type": "object"}, "maxItems": 32}


def _closed_object_schema(
    schema_id: str,
    *,
    required: list[str],
    properties: dict[str, Any],
) -> dict[str, Any]:
    schema = open_object_schema(schema_id, required=required, properties=properties)
    schema["additionalProperties"] = False
    return schema


WORKFLOW_CONTINUATION_BATCH_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-workflow-continuation-input-bundle.v1": _closed_object_schema(
        "agent-workflow-continuation-input-bundle.v1",
        required=["schemaVersion", "runId", "packageId", "planDigest", "sourceRevision", "steps"],
        properties={
            "runId": {"type": "string", "minLength": 1, "maxLength": 256},
            "packageId": {"type": "string", "minLength": 1, "maxLength": 256},
            "planDigest": _DIGEST,
            "sourceRevision": {"type": "string", "minLength": 1, "maxLength": 4096},
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_CONTINUATION_BATCH_STEPS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["operationId", "expectedActionType", "inputs"],
                    "properties": {
                        "operationId": {"type": "string", "minLength": 1, "maxLength": 256},
                        "expectedActionType": {"type": "string", "minLength": 1, "maxLength": 128},
                        "inputs": {"type": "object"},
                    },
                },
            },
        },
    ),
    "agent-workflow-continuation-batch-receipt.v1": open_object_schema(
        "agent-workflow-continuation-batch-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "stopReason",
            "receiptPath",
            "bundle",
            "lineage",
            "limits",
            "inputBytes",
            "outputBytes",
            "steps",
            "appliedCount",
            "alreadyAppliedCount",
            "lastAppliedOperationId",
            "finalState",
            "nextCommand",
            "requiredInputs",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["IN_PROGRESS", "STOPPED", "COMPLETE"]},
            "stopReason": {"type": ["string", "null"], "enum": [None, *CONTINUATION_BATCH_STOP_REASONS]},
            "receiptPath": {"type": "string", "minLength": 1, "maxLength": 4096},
            "bundle": {"type": ["object", "null"]},
            "lineage": {"type": ["object", "null"]},
            "limits": {"type": "object"},
            "inputBytes": {"type": "integer", "minimum": 0},
            "outputBytes": {"type": "integer", "minimum": 0},
            "steps": {
                "type": "array",
                "maxItems": MAX_CONTINUATION_BATCH_STEPS,
                "items": {"type": "object"},
            },
            "appliedCount": {"type": "integer", "minimum": 0, "maximum": MAX_CONTINUATION_BATCH_STEPS},
            "alreadyAppliedCount": {
                "type": "integer",
                "minimum": 0,
                "maximum": MAX_CONTINUATION_BATCH_STEPS,
            },
            "lastAppliedOperationId": {"type": ["string", "null"]},
            "finalState": {"type": ["object", "null"]},
            "nextCommand": {"type": ["string", "null"]},
            "requiredInputs": _REQUIRED_INPUTS,
            "blockers": _BLOCKERS,
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    "agent-workflow-continuation-batch-summary.v1": open_object_schema(
        "agent-workflow-continuation-batch-summary.v1",
        required=[
            "schemaVersion",
            "status",
            "stopReason",
            "appliedCount",
            "alreadyAppliedCount",
            "lastAppliedOperationId",
            "finalState",
            "receiptPath",
            "receiptDigest",
            "inputBytes",
            "outputBytes",
            "nextCommand",
            "requiredInputs",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "summaryDigest",
        ],
        properties={
            "status": {"enum": ["STOPPED", "COMPLETE"]},
            "stopReason": {"enum": list(CONTINUATION_BATCH_STOP_REASONS)},
            "appliedCount": {"type": "integer", "minimum": 0},
            "alreadyAppliedCount": {"type": "integer", "minimum": 0},
            "lastAppliedOperationId": {"type": ["string", "null"]},
            "finalState": {"type": ["object", "null"]},
            "receiptPath": {"type": ["string", "null"]},
            "receiptDigest": {"type": ["string", "null"], "minLength": 64, "maxLength": 64},
            "inputBytes": {"type": "integer", "minimum": 0},
            "outputBytes": {"type": "integer", "minimum": 0},
            "nextCommand": {"type": ["string", "null"]},
            "requiredInputs": _REQUIRED_INPUTS,
            "blockers": _BLOCKERS,
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "summaryDigest": _DIGEST,
        },
    ),
}


def build_continuation_batch_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    """Build the bounded stdout projection of one persisted batch receipt."""

    body = {
        "schemaVersion": "agent-workflow-continuation-batch-summary.v1",
        "status": receipt["status"],
        "stopReason": receipt["stopReason"],
        "appliedCount": receipt["appliedCount"],
        "alreadyAppliedCount": receipt["alreadyAppliedCount"],
        "lastAppliedOperationId": receipt["lastAppliedOperationId"],
        "finalState": receipt["finalState"],
        "receiptPath": receipt["receiptPath"],
        "receiptDigest": receipt["receiptDigest"],
        "inputBytes": receipt["inputBytes"],
        "outputBytes": receipt["outputBytes"],
        "nextCommand": receipt["nextCommand"],
        "requiredInputs": receipt["requiredInputs"],
        "blockers": receipt["blockers"],
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "summaryDigest": canonical_digest(body)}


def build_unpersisted_continuation_batch_summary(
    *,
    stop_reason: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a fail-closed summary when no output receipt can be reserved."""

    body = {
        "schemaVersion": "agent-workflow-continuation-batch-summary.v1",
        "status": "STOPPED",
        "stopReason": stop_reason,
        "appliedCount": 0,
        "alreadyAppliedCount": 0,
        "lastAppliedOperationId": None,
        "finalState": None,
        "receiptPath": None,
        "receiptDigest": None,
        "inputBytes": 0,
        "outputBytes": 0,
        "nextCommand": None,
        "requiredInputs": [],
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "summaryDigest": canonical_digest(body)}


def continuation_batch_blocker(exc: LifecycleError) -> dict[str, Any]:
    """Convert one lifecycle failure into a stable batch blocker."""

    blocker: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        blocker["context"] = exc.details
    return blocker


def continuation_batch_stop_reason(exc: LifecycleError) -> str:
    """Map preflight failures to the closed batch stop-reason set."""

    if exc.code == "continuation-retry-proof-required":
        return "RETRY_PROOF_REQUIRED"
    if exc.code == "continuation-retry-proof-mismatch":
        return "RETRY_PROOF_MISMATCH"
    if exc.code == "continuation-input-cap-exceeded":
        return "CAP_BYTES"
    return "BLOCKED"


def continuation_batch_projection_fields(
    projection: dict[str, Any] | None,
) -> tuple[str | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract bounded operator-facing fields from a one-step projection."""

    if projection is None:
        return "workflow continue", [], []
    action = projection.get("action")
    next_action = projection.get("nextAction")
    route = action.get("route") if isinstance(action, dict) else None
    if not isinstance(route, str) and isinstance(next_action, dict):
        route = next_action.get("type")
    return (
        f"workflow {route}" if isinstance(route, str) else None,
        list(projection.get("requiredInputs", [])),
        list(projection.get("blockers", [])),
    )


def is_sha256_digest(value: Any) -> bool:
    """Return whether value is one lowercase SHA-256 hexadecimal digest."""

    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def normalize_continuation_input_reference(value: Any, field: str) -> dict[str, str]:
    """Validate one digest-bound repository-relative artifact reference."""

    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise LifecycleError("continuation-input-reference-invalid", f"{field} must be a path and SHA-256 reference")
    raw_path = value.get("path")
    digest = value.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(digest, str) or not is_sha256_digest(digest):
        raise LifecycleError("continuation-input-reference-invalid", f"{field} sha256 is invalid")
    path = normalize_repo_path(raw_path, label=field)
    return {"path": path, "sha256": digest}


__all__ = [
    "CONTINUATION_BATCH_STOP_REASONS",
    "MAX_CONTINUATION_BATCH_STEPS",
    "WORKFLOW_CONTINUATION_BATCH_SCHEMAS",
    "build_continuation_batch_summary",
    "build_unpersisted_continuation_batch_summary",
    "continuation_batch_blocker",
    "continuation_batch_projection_fields",
    "continuation_batch_stop_reason",
    "is_sha256_digest",
    "normalize_continuation_input_reference",
]
