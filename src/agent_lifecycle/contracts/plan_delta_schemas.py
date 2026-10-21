"""Portable contracts for project principles and plan-delta reports."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

PROJECT_PRINCIPLES_SCHEMA = "agent-project-principles.v1"
PROJECT_PRINCIPLES_VALIDATION_SCHEMA = "agent-project-principles-validation.v1"
PLAN_DELTA_SCHEMA = "agent-plan-delta.v1"
PLAN_DELTA_VALIDATION_SCHEMA = "agent-plan-delta-validation.v1"
PLAN_IMPACT_GRAPH_SCHEMA = "agent-plan-impact-graph.v1"
DELTA_REVIEW_SCHEMA = "agent-plan-delta-review.v1"
IMPACT_SELECTION_SCHEMA = "agent-plan-impact-selection.v1"
REVIEW_SCOPE_SCHEMA = "agent-plan-review-scope.v1"
COMPOSITE_REVIEW_SCHEMA = "agent-plan-composite-review.v1"
PLAN_LOCK_SCOPE_SCHEMA = "agent-plan-lock.v3"
MAX_REVIEW_REPORTS = 16
MAX_REVIEW_DEPENDENCY_EDGES = 8
MAX_REVIEW_CHAIN_BYTES = 8 * 1024 * 1024
MAX_IMPACT_NODES = 4096
MAX_IMPACT_EDGES = 16384

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_OPTIONAL_DIGEST = {"type": ["string", "null"], "minLength": 0, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 128}
_BOUNDED_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_BOUNDED_TEXT = {"type": "string", "minLength": 1, "maxLength": 2048}
_BOUNDED_LIST = {"type": "array", "items": _BOUNDED_TEXT, "maxItems": 32}


PLAN_DELTA_SCHEMAS: dict[str, dict[str, Any]] = {
    IMPACT_SELECTION_SCHEMA: open_object_schema(
        IMPACT_SELECTION_SCHEMA,
        required=["mode", "baseHash", "candidateHash", "closure", "selectionDigest"],
        properties={
            "mode": {"enum": ["DELTA_ELIGIBLE", "FULL_REQUIRED"]},
            "baseHash": _DIGEST,
            "candidateHash": _DIGEST,
            "closure": {"type": "array", "items": _BOUNDED_TEXT},
            "selectionDigest": _DIGEST,
        },
    ),
    COMPOSITE_REVIEW_SCHEMA: open_object_schema(
        COMPOSITE_REVIEW_SCHEMA,
        required=[
            "packageId",
            "planRevision",
            "reviewId",
            "reviewedPlanHash",
            "fullReview",
            "verdict",
            "reviewScope",
            "reportBindings",
        ],
        properties={
            "fullReview": {"const": False},
            "verdict": {"const": "READY_TO_FREEZE"},
            "reviewedPlanHash": _DIGEST,
            "reviewScope": {"type": "object"},
            "reportBindings": {"type": "object", "maxProperties": 128},
        },
    ),
    "agent-plan-review.v2": open_object_schema(
        "agent-plan-review.v2",
        required=[
            "packageId",
            "planRevision",
            "reviewId",
            "reviewedPlanHash",
            "fullReview",
            "reviewer",
            "verdict",
            "findings",
            "subject",
            "reviewScope",
            "reviewAuthority",
        ],
        properties={
            "reviewedPlanHash": _DIGEST,
            "fullReview": {"type": "boolean"},
            "reviewer": {"type": "object"},
            "subject": {"type": "object"},
            "verdict": {"enum": ["READY_TO_FREEZE", "ACCEPTED", "CHANGES_REQUIRED", "BLOCKED"]},
            "findings": {"type": "array", "maxItems": 128},
            "reviewScope": {"type": "object"},
            "reviewAuthority": {"type": "object"},
        },
    ),
    PLAN_IMPACT_GRAPH_SCHEMA: open_object_schema(
        PLAN_IMPACT_GRAPH_SCHEMA,
        required=["manifestHash", "nodes", "edges", "graphDigest"],
        properties={
            "manifestHash": _DIGEST,
            "nodes": {
                "type": "array",
                "maxItems": MAX_IMPACT_NODES,
                "items": {"type": "object"},
            },
            "edges": {
                "type": "array",
                "maxItems": MAX_IMPACT_EDGES,
                "items": {"type": "object"},
            },
            "graphDigest": _DIGEST,
        },
    ),
    REVIEW_SCOPE_SCHEMA: open_object_schema(
        REVIEW_SCOPE_SCHEMA,
        required=["kind", "candidateHash", "graphDigest", "coveredNodes"],
        properties={
            "kind": {"enum": ["FULL", "DELTA", "COMPOSITE"]},
            "candidateHash": _DIGEST,
            "graphDigest": _DIGEST,
            "coveredNodes": {
                "type": "array",
                "maxItems": MAX_IMPACT_NODES,
                "items": _BOUNDED_TEXT,
                "uniqueItems": True,
            },
        },
    ),
    DELTA_REVIEW_SCHEMA: open_object_schema(
        DELTA_REVIEW_SCHEMA,
        required=[
            "mode",
            "reasons",
            "baseHash",
            "candidateHash",
            "changedNodes",
            "closure",
            "readOnly",
            "packetDigest",
        ],
        properties={
            "mode": {"enum": ["FULL", "DELTA_ELIGIBLE", "FULL_REQUIRED"]},
            "reasons": _BOUNDED_LIST,
            "baseHash": {"type": ["string", "null"]},
            "candidateHash": _DIGEST,
            "changedNodes": {"type": "array", "items": _BOUNDED_TEXT},
            "closure": {"type": "array", "items": _BOUNDED_TEXT},
            "readOnly": {"const": True},
            "packetDigest": _DIGEST,
        },
    ),
    PROJECT_PRINCIPLES_SCHEMA: open_object_schema(
        PROJECT_PRINCIPLES_SCHEMA,
        required=[
            "schemaVersion",
            "principlesId",
            "revision",
            "entries",
            "authority",
            "source",
            "productionPromotionClaimed",
            "principlesDigest",
        ],
        properties={
            "principlesId": _BOUNDED_ID,
            "revision": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "entries": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "object"}},
            "authority": {"type": "object", "maxProperties": 8},
            "source": {"type": "object", "maxProperties": 8},
            "productionPromotionClaimed": {"const": False},
            "principlesDigest": _DIGEST,
        },
    ),
    PROJECT_PRINCIPLES_VALIDATION_SCHEMA: open_object_schema(
        PROJECT_PRINCIPLES_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "principlesDigest",
            "entryCount",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "principlesDigest": _OPTIONAL_DIGEST,
            "entryCount": {"type": "integer", "minimum": 0, "maximum": 32},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    PLAN_DELTA_SCHEMA: open_object_schema(
        PLAN_DELTA_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "before",
            "after",
            "lineage",
            "changes",
            "authorityImpact",
            "reviewRequired",
            "newLockRequired",
            "readOnly",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "deltaDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "BLOCKED"]},
            "before": {"type": "object", "maxProperties": 16},
            "after": {"type": "object", "maxProperties": 16},
            "lineage": {"type": "object", "maxProperties": 16},
            "changes": {"type": "object", "maxProperties": 32},
            "authorityImpact": {"type": "object", "maxProperties": 16},
            "reviewRequired": {"type": "boolean"},
            "newLockRequired": {"type": "boolean"},
            "readOnly": {"const": True},
            "blockers": _BLOCKERS,
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "deltaDigest": _DIGEST,
        },
    ),
    PLAN_DELTA_VALIDATION_SCHEMA: open_object_schema(
        PLAN_DELTA_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "deltaStatus",
            "reviewRequired",
            "newLockRequired",
            "blockers",
            "deltaDigest",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "deltaStatus": {"type": ["string", "null"]},
            "reviewRequired": {"type": "boolean"},
            "newLockRequired": {"type": "boolean"},
            "blockers": _BLOCKERS,
            "deltaDigest": _OPTIONAL_DIGEST,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}
