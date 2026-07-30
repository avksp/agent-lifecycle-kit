"""Built-in JSON schema definitions for a lifecycle contract domain."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

RELEASE_CONTRACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-release-candidate-inventory.v1": _open_object_schema(
        "agent-release-candidate-inventory.v1",
        required=[
            "schemaVersion",
            "packageId",
            "planRevision",
            "planDigest",
            "files",
            "candidatePayloadInventoryDigest",
        ],
        properties={
            "packageId": {"type": "string", "minLength": 1},
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "files": {"type": "array", "items": {"type": "object"}},
            "candidatePayloadInventoryDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-release-assembly-evidence.v1": _open_object_schema(
        "agent-release-assembly-evidence.v1",
        required=["schemaVersion", "status", "inventory", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "inventory": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-release-verification-evidence.v1": _open_object_schema(
        "agent-release-verification-evidence.v1",
        required=["schemaVersion", "status", "inventory", "mismatches", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "inventory": {"type": "object"},
            "mismatches": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-final-candidate-audit.v1": _open_object_schema(
        "agent-final-candidate-audit.v1",
        required=["schemaVersion", "status", "planRevision", "planDigest", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "semanticStatus": {"type": "string", "minLength": 1},
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-support-matrix-contract-evidence.v1": _open_object_schema(
        "agent-support-matrix-contract-evidence.v1",
        required=["schemaVersion", "status", "adapterMaturity", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterMaturity": {"type": "string", "minLength": 1},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-deferred-promotion-contract-evidence.v1": _open_object_schema(
        "agent-deferred-promotion-contract-evidence.v1",
        required=["schemaVersion", "status", "deferredProductionPromotion", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "deferredProductionPromotion": {"const": True},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-neutrality-report.v1": _open_object_schema(
        "agent-neutrality-report.v1",
        required=["schemaVersion", "counters"],
        properties={
            "counters": {"type": "object"},
            "operation": {"type": "object"},
        },
    ),
    "agent-live-calibration-verification.v1": _open_object_schema(
        "agent-live-calibration-verification.v1",
        required=["schemaVersion", "status", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-lifecycle-live-calibration-receipt.v1": _open_object_schema(
        "agent-lifecycle-live-calibration-receipt.v1",
        required=["schemaVersion", "status", "host", "runs", "syntheticReplayUsed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "host": {"type": "string", "minLength": 1},
            "runs": {"type": "array", "items": {"type": "object"}},
            "syntheticReplayUsed": {"const": False},
        },
    ),
    "agent-lifecycle-live-host-conformance-receipt.v1": _open_object_schema(
        "agent-lifecycle-live-host-conformance-receipt.v1",
        required=["schemaVersion", "status", "host", "operations", "syntheticReplayUsed", "usageAttested"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "host": {"type": "string", "minLength": 1},
            "operations": {"type": "array", "items": {"type": "object"}},
            "syntheticReplayUsed": {"const": False},
            "usageAttested": {"const": True},
        },
    ),
    "agent-live-host-conformance-verification.v1": _open_object_schema(
        "agent-live-host-conformance-verification.v1",
        required=["schemaVersion", "status", "promotedHosts", "checks", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "promotedHosts": {"type": "array", "items": {"type": "string"}},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-live-host-promotion-plan.v1": _open_object_schema(
        "agent-live-host-promotion-plan.v1",
        required=[
            "schemaVersion",
            "packageId",
            "sddTier",
            "status",
            "intent",
            "hostOrder",
            "sequencingPolicy",
            "hostAvailabilitySnapshot",
            "sharedInputs",
            "artifactRootPolicy",
            "budgetPolicy",
            "blockerCodes",
            "operationEvidenceRequirements",
            "validationCommands",
            "evidenceArtifacts",
            "workstreams",
            "acceptanceCriteria",
        ],
        properties={
            "packageId": {"type": "string", "minLength": 1},
            "sddTier": {"enum": ["S0", "S1", "S2"]},
            "status": {"enum": ["DRAFT", "READY", "FROZEN", "BLOCKED"]},
            "intent": {"type": "string", "minLength": 1},
            "hostOrder": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "sequencingPolicy": {"type": "object"},
            "hostAvailabilitySnapshot": {"type": "object"},
            "sharedInputs": {"type": "object"},
            "artifactRootPolicy": {"type": "object"},
            "budgetPolicy": {"type": "object"},
            "blockerCodes": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "operationEvidenceRequirements": {"type": "object"},
            "validationCommands": {"type": "array", "items": {"type": "object"}},
            "evidenceArtifacts": {"type": "array", "items": {"type": "object"}},
            "workstreams": {"type": "array", "items": {"type": "object"}},
            "acceptanceCriteria": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-live-host-promotion-plan-validation.v1": _open_object_schema(
        "agent-live-host-promotion-plan-validation.v1",
        required=["schemaVersion", "status", "plan", "checks", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "plan": {"type": "object"},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-digest-authority-evidence.v1": _open_object_schema(
        "agent-digest-authority-evidence.v1",
        required=["schemaVersion", "status", "canonicalAuthority", "checks", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "canonicalAuthority": {"type": "string", "minLength": 1},
            "checks": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-docs-compat-evidence.v1": _open_object_schema(
        "agent-docs-compat-evidence.v1",
        required=["schemaVersion", "status", "checks", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-negative-suite-coverage.v1": _open_object_schema(
        "agent-negative-suite-coverage.v1",
        required=["schemaVersion", "status", "expectedRange", "coveredScenarios"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "expectedRange": {"type": "string", "minLength": 1},
            "coveredScenarios": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-task-packet-context-fit.v1": _open_object_schema(
        "agent-task-packet-context-fit.v1",
        required=["schemaVersion", "status", "targetWindows", "checks"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "targetWindows": {"type": "array", "items": {"type": "string"}},
            "checks": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-packaging-smoke-evidence.v1": _open_object_schema(
        "agent-packaging-smoke-evidence.v1",
        required=["schemaVersion", "status", "commands", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "commands": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-adapter-scaffold-result.v1": _open_object_schema(
        "agent-adapter-scaffold-result.v1",
        required=["schemaVersion", "status", "host", "maturity", "files", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "DRY_RUN"]},
            "host": {"type": "string", "minLength": 1},
            "maturity": {"const": "EXPERIMENTAL"},
            "files": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-workflow-lineage-check.v1": _open_object_schema(
        "agent-workflow-lineage-check.v1",
        required=["schemaVersion", "status", "planRevision", "planDigest", "lineageChecks"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "lineageChecks": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-public-contract-policy.v1": _open_object_schema(
        "agent-public-contract-policy.v1",
        required=[
            "schemaVersion",
            "status",
            "rules",
            "requiredCoreSchemas",
            "schemas",
            "cliOutputs",
            "productionPromotionClaimed",
            "policyDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "rules": {"type": "object"},
            "requiredCoreSchemas": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "schemas": {"type": "array", "items": {"type": "object"}},
            "cliOutputs": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "policyDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-public-contract-policy-validation.v1": _open_object_schema(
        "agent-public-contract-policy-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "schemaCount",
            "cliOutputCount",
            "deprecatedCompatibleSchemas",
            "blockers",
            "policyDigest",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "schemaCount": {"type": "integer", "minimum": 0},
            "cliOutputCount": {"type": "integer", "minimum": 0},
            "deprecatedCompatibleSchemas": {"type": "array", "items": {"type": "string"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "policyDigest": {"type": ["string", "null"]},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}
