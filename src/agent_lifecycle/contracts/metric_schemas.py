"""JSON schema definitions for lifecycle metrics contracts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

METRIC_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-lifecycle-cost-report.v1": open_object_schema(
        "agent-lifecycle-cost-report.v1",
        required=["schemaVersion", "mode", "entries"],
        properties={
            "mode": {"enum": ["light", "standard", "strict", "release"]},
            "entries": {"type": "array", "items": {"type": "object"}},
            "generatedBy": {"type": "string"},
            "sourceArtifacts": {"type": "array", "items": {"type": "object"}},
            "lineage": {"type": "object"},
            "usageConfidence": {"type": "object"},
            "compactSummary": {"type": "object"},
            "limits": {"type": "object"},
            "overLimitReason": {"type": "string"},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-lifecycle-cost-validation.v1": open_object_schema(
        "agent-lifecycle-cost-validation.v1",
        required=["schemaVersion", "status", "mode", "totals", "ratios", "limits", "blockers", "reportDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "mode": {"type": ["string", "null"]},
            "totals": {"type": "object"},
            "ratios": {"type": "object"},
            "usageConfidence": {"type": "object"},
            "limits": {"type": "object"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "reportDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-lifecycle-cost-generation.v1": open_object_schema(
        "agent-lifecycle-cost-generation.v1",
        required=["schemaVersion", "status", "reportPath", "reportDigest", "validation"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "reportPath": {"type": "string"},
            "reportBytes": {"type": "integer", "minimum": 0},
            "reportDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "summaryPath": {"type": ["string", "null"]},
            "summaryDigest": {"type": ["string", "null"]},
            "validation": {"type": "object"},
            "liveCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-lifecycle-cost-summary.v1": open_object_schema(
        "agent-lifecycle-cost-summary.v1",
        required=[
            "schemaVersion",
            "mode",
            "latestUserIntent",
            "activeDecisions",
            "openBlockers",
            "acceptedEvidence",
            "changedFiles",
            "nextRequiredAction",
            "doNotDo",
            "categoryTotals",
            "ratios",
            "usageConfidence",
        ],
        properties={
            "mode": {"type": ["string", "null"]},
            "activeDecisions": {"type": "array", "items": {"type": "string"}},
            "openBlockers": {"type": "array"},
            "acceptedEvidence": {"type": "array", "items": {"type": "object"}},
            "changedFiles": {"type": "array", "items": {"type": "string"}},
            "nextRequiredAction": {"type": "string"},
            "doNotDo": {"type": "array", "items": {"type": "string"}},
            "categoryTotals": {"type": "object"},
            "ratios": {"type": "object"},
            "usageConfidence": {"type": "object"},
            "usefulWorkTokens": {"type": "integer", "minimum": 0},
            "processOverheadTokens": {"type": "integer", "minimum": 0},
        },
    ),
}
