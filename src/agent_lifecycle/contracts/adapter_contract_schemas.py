"""Built-in JSON schema definitions for a lifecycle contract domain."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

ADAPTER_CONTRACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-host-adapter-validation.v1": _open_object_schema(
        "agent-host-adapter-validation.v1",
        required=["schemaVersion", "status", "adapterId", "host", "maturity", "blockers"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "maturity": {"type": ["string", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-readiness-report.v1": _open_object_schema(
        "agent-readiness-report.v1",
        required=["schemaVersion", "status", "summary", "checks", "adapters", "evidence"],
        properties={
            "status": {"enum": ["PASS", "WARN", "FAIL"]},
            "summary": {"type": "object"},
            "checks": {"type": "array", "items": {"type": "object"}},
            "adapters": {"type": "array", "items": {"type": "object"}},
            "evidence": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
            "maturityChangesClaimed": {"const": False},
        },
    ),
    "agent-adapter-install-plan.v1": _open_object_schema(
        "agent-adapter-install-plan.v1",
        required=["schemaVersion", "status", "host", "maturity", "files", "commands"],
        properties={
            "status": {"const": "DRY_RUN"},
            "host": {"type": "string", "minLength": 1},
            "maturity": {"enum": ["EXPERIMENTAL", "VERIFIED"]},
            "files": {"type": "array", "items": {"type": "object"}},
            "commands": {"type": "array", "items": {"type": "object"}},
            "writesStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "maturityChangeClaimed": {"const": False},
        },
    ),
    "agent-host-adapter-inspection.v1": _open_object_schema(
        "agent-host-adapter-inspection.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "host",
            "maturity",
            "descriptorDigest",
            "liveCallsStarted",
            "productionPromotionClaimed",
            "capabilities",
            "checks",
            "blockers",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "maturity": {"type": ["string", "null"]},
            "descriptorDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "liveCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "capabilities": {"type": "object"},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-adapter-capability-manifest.v1": _open_object_schema(
        "agent-adapter-capability-manifest.v1",
        required=[
            "schemaVersion",
            "adapterId",
            "host",
            "maturity",
            "descriptorDigest",
            "unsupportedOperationPolicy",
            "coreSemantics",
            "capabilities",
            "modelRouting",
            "runtimeBoundary",
            "promotion",
        ],
        properties={
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "maturity": {"type": ["string", "null"]},
            "descriptorDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "unsupportedOperationPolicy": {"const": "fail-closed"},
            "coreSemantics": {"const": "delegated-to-agent-lifecycle-core"},
            "capabilities": {"type": "array", "items": {"type": "object"}},
            "modelRouting": {"type": "object"},
            "runtimeBoundary": {"type": "object"},
            "hostCapabilities": {"type": "array", "items": {"type": "object"}},
            "sandboxCapabilities": {"type": ["object", "null"]},
            "promotion": {"type": "object"},
        },
    ),
    "agent-adapter-capability-manifest-validation.v1": _open_object_schema(
        "agent-adapter-capability-manifest-validation.v1",
        required=["schemaVersion", "status", "adapterId", "host", "maturity", "capabilityCount", "blockers"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "maturity": {"type": ["string", "null"]},
            "capabilityCount": {"type": "integer", "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-adapter-conformance-verification.v1": _open_object_schema(
        "agent-adapter-conformance-verification.v1",
        required=["schemaVersion", "status", "baseline", "hosts", "checks", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "baseline": {"type": "object"},
            "hosts": {"type": "array", "items": {"type": "string"}},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
}
