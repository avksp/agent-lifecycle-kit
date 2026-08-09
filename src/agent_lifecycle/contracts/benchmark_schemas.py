"""Built-in JSON schemas for deterministic reference-task evaluation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema


BENCHMARK_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-reference-task-suite.v1": open_object_schema(
        "agent-reference-task-suite.v1",
        required=["schemaVersion", "suiteId", "suiteVersion", "tasks", "productionPromotionClaimed"],
        properties={
            "suiteId": {"type": "string", "minLength": 1},
            "suiteVersion": {"type": "string", "minLength": 1},
            "tasks": {"type": "array", "minItems": 1, "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-reference-task-oracle.v1": open_object_schema(
        "agent-reference-task-oracle.v1",
        required=[
            "schemaVersion",
            "taskId",
            "taskVersion",
            "oracleType",
            "requiredEvidenceSchemas",
            "productionPromotionClaimed",
        ],
        properties={
            "taskId": {"type": "string", "minLength": 1},
            "taskVersion": {"type": "string", "minLength": 1},
            "oracleType": {
                "enum": ["planning", "architecture-review", "bug-forensics", "s1-managed-task", "s2-evidence-task"]
            },
            "requiredEvidenceSchemas": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-reference-task-submission.v1": open_object_schema(
        "agent-reference-task-submission.v1",
        required=["schemaVersion", "taskId", "taskVersion", "accepted", "evidence", "productionPromotionClaimed"],
        properties={
            "taskId": {"type": "string", "minLength": 1},
            "taskVersion": {"type": "string", "minLength": 1},
            "accepted": {"type": "boolean"},
            "evidence": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-reference-task-evaluation.v1": open_object_schema(
        "agent-reference-task-evaluation.v1",
        required=[
            "schemaVersion",
            "status",
            "suite",
            "task",
            "inputArtifacts",
            "oracle",
            "measurements",
            "summary",
            "redaction",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "evaluationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "suite": {"type": "object"},
            "task": {"type": "object"},
            "inputArtifacts": {"type": "array", "items": {"type": "object"}},
            "oracle": {"type": "object"},
            "measurements": {"type": "object"},
            "summary": {"type": "object"},
            "redaction": {"type": "object"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "evaluationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}
