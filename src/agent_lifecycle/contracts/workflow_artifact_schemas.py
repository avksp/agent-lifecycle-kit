"""Schemas for task attempts, remediation, and freshness evidence."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_GIT_COMMIT = {"type": "string", "minLength": 40, "maxLength": 64}
_IDENTITY = {
    "type": "object",
    "required": ["path", "sha256", "bytes"],
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "sha256": _DIGEST,
        "bytes": {"type": "integer", "minimum": 1},
    },
}
_FILE_IDENTITY = {
    "type": "object",
    "required": ["path", "kind", "mode", "sha256", "bytes"],
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "kind": {"enum": ["file", "symlink", "missing"]},
        "mode": {"type": ["string", "null"]},
        "sha256": {"oneOf": [_DIGEST, {"type": "null"}]},
        "bytes": {"type": "integer", "minimum": 0},
    },
}

WORKFLOW_ARTIFACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-task-change-set-claim.v1": open_object_schema(
        "agent-task-change-set-claim.v1",
        required=["schemaVersion", "provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash"],
        properties={
            "provider": {"const": "git-worktree-v2"},
            "baselineSha": _GIT_COMMIT,
            "fileSetHash": _DIGEST,
            "diffHash": _DIGEST,
            "snapshotHash": _DIGEST,
        },
    ),
    "agent-task-change-set-evidence.v1": open_object_schema(
        "agent-task-change-set-evidence.v1",
        required=[
            "schemaVersion",
            "provider",
            "baselineSha",
            "changedFiles",
            "allChangedFiles",
            "fileSetHash",
            "diffHash",
            "snapshotHash",
            "changedFileCount",
            "repositoryChangedFileCount",
            "contentBytes",
        ],
        properties={
            "provider": {"const": "git-worktree-v2"},
            "baselineSha": _GIT_COMMIT,
            "changedFiles": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "allChangedFiles": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "entries": {"type": "array", "maxItems": 10000, "items": _FILE_IDENTITY},
            "fileSetHash": _DIGEST,
            "diffHash": _DIGEST,
            "snapshotHash": _DIGEST,
            "changedFileCount": {"type": "integer", "minimum": 0},
            "repositoryChangedFileCount": {"type": "integer", "minimum": 0},
            "contentBytes": {"type": "integer", "minimum": 0},
        },
    ),
    "agent-task-attempt-history-entry.v1": open_object_schema(
        "agent-task-attempt-history-entry.v1",
        required=[
            "schemaVersion",
            "runId",
            "packageId",
            "taskId",
            "attempt",
            "planRevision",
            "planDigest",
            "sourceRevision",
            "result",
            "review",
            "implementationAuditReport",
            "findingIds",
            "archivedAt",
        ],
        properties={
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": "string", "minLength": 1},
            "taskId": {"type": "string", "minLength": 1},
            "attempt": {"type": "integer", "minimum": 1},
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "sourceRevision": {"type": "string", "minLength": 1},
            "result": _IDENTITY,
            "review": _IDENTITY,
            "implementationAuditReport": {"oneOf": [_IDENTITY, {"type": "null"}]},
            "findingIds": {
                "type": "array",
                "minItems": 1,
                "maxItems": 128,
                "items": {"type": "string", "minLength": 1, "maxLength": 256},
            },
            "archivedAt": {"type": "string", "minLength": 1},
        },
    ),
    "agent-rework-delta-audit-receipt.v1": open_object_schema(
        "agent-rework-delta-audit-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "disposition",
            "runId",
            "packageId",
            "taskId",
            "previousAttempt",
            "currentAttempt",
            "planLineage",
            "attemptArtifacts",
            "attemptDelta",
            "findingDispositions",
            "validationSelection",
            "dependencyReportDigest",
            "commandsExecuted",
            "modelCallsStarted",
            "hostLaunchStarted",
            "authorityClaimed",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "disposition": {"enum": ["DELTA_REVIEW_AVAILABLE", "FULL_AUDIT_REQUIRED", "BLOCKED"]},
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": "string", "minLength": 1},
            "taskId": {"type": "string", "minLength": 1},
            "previousAttempt": {"type": "integer", "minimum": 1},
            "currentAttempt": {"type": "integer", "minimum": 2},
            "planLineage": {"type": "object"},
            "attemptArtifacts": {"type": "object"},
            "attemptDelta": {"type": "object"},
            "findingDispositions": {"type": "array", "maxItems": 128, "items": {"type": "object"}},
            "validationSelection": {"type": "object"},
            "dependencyReportDigest": {"oneOf": [_DIGEST, {"type": "null"}]},
            "commandsExecuted": {"const": False},
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "authorityClaimed": {"const": False},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 128},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
}


__all__ = ["WORKFLOW_ARTIFACT_SCHEMAS"]
