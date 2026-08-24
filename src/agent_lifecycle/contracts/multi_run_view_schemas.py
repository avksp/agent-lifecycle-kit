"""Contracts for bounded, read-only views over several lifecycle runs."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 64}

MULTI_RUN_ATTENTION_ITEM_SCHEMA = "agent-multi-run-attention-item.v1"
MULTI_RUN_OVERLAP_SCHEMA = "agent-multi-run-overlap.v1"
MULTI_RUN_VIEW_SCHEMA = "agent-multi-run-attention-view.v1"

MULTI_RUN_VIEW_SCHEMAS: dict[str, dict[str, Any]] = {
    MULTI_RUN_ATTENTION_ITEM_SCHEMA: open_object_schema(
        MULTI_RUN_ATTENTION_ITEM_SCHEMA,
        required=[
            "schemaVersion",
            "itemId",
            "reasonCode",
            "severity",
            "runId",
            "packageId",
            "planRevision",
            "planDigest",
            "sourceRevision",
            "stateRevision",
        ],
        properties={
            "itemId": {"type": "string", "minLength": 1, "maxLength": 256},
            "reasonCode": {"enum": [
                "BLOCKER_PRESENT",
                "USER_ACTION_REQUIRED",
                "PENDING_REVIEW",
                "STALE_ATTEMPT",
                "FAILED_EVIDENCE",
                "TERMINAL_RUN",
                "SOURCE_UNAVAILABLE",
            ]},
            "severity": {"enum": ["HIGH", "MEDIUM", "LOW", "INFO"]},
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": ["string", "null"]},
            "planRevision": {"type": ["integer", "null"], "minimum": 0},
            "planDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "sourceRevision": {"type": ["string", "null"]},
            "stateRevision": {"type": ["integer", "null"], "minimum": 1},
            "taskId": {"type": ["string", "null"]},
            "phase": {"type": ["string", "null"]},
            "message": {"type": "string", "maxLength": 512},
            "sourcePath": {"type": ["string", "null"]},
            "blockerCode": {"type": ["string", "null"]},
        },
    ),
    MULTI_RUN_OVERLAP_SCHEMA: open_object_schema(
        MULTI_RUN_OVERLAP_SCHEMA,
        required=["schemaVersion", "overlapId", "path", "runIds", "authorityRetained"],
        properties={
            "overlapId": {"type": "string", "minLength": 1, "maxLength": 256},
            "path": {"type": "string", "minLength": 1},
            "runIds": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 1}},
            "packageIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "planRevisions": {"type": "array", "items": {"type": "integer", "minimum": 0}},
            "authorityRetained": {"const": True},
            "reasonCode": {"const": "DECLARED_PATH_OVERLAP"},
        },
    ),
    MULTI_RUN_VIEW_SCHEMA: open_object_schema(
        MULTI_RUN_VIEW_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "sourceOfTruth",
            "readOnly",
            "modelCallsStarted",
            "stateWritten",
            "projectRoot",
            "sourceCount",
            "sources",
            "attentionItems",
            "overlaps",
            "blockers",
            "productionPromotionClaimed",
            "viewDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "sourceOfTruth": {"const": False},
            "readOnly": {"const": True},
            "modelCallsStarted": {"const": False},
            "stateWritten": {"const": False},
            "projectRoot": {"const": "<checkout>"},
            "sourceCount": {"type": "integer", "minimum": 0},
            "successfulSourceCount": {"type": "integer", "minimum": 0},
            "failedSourceCount": {"type": "integer", "minimum": 0},
            "sources": {"type": "array", "items": {"type": "object"}},
            "attentionItems": {"type": "array", "items": {"type": "object"}},
            "overlaps": {"type": "array", "items": {"type": "object"}},
            "blockers": _BLOCKERS,
            "limits": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
            "viewDigest": _DIGEST,
        },
    ),
}


__all__ = [
    "MULTI_RUN_ATTENTION_ITEM_SCHEMA",
    "MULTI_RUN_OVERLAP_SCHEMA",
    "MULTI_RUN_VIEW_SCHEMA",
    "MULTI_RUN_VIEW_SCHEMAS",
]
