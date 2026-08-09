"""Built-in JSON schema registry for portable lifecycle envelopes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts.adapter_contract_schemas import ADAPTER_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.adapter_event_schemas import ADAPTER_EVENT_SCHEMAS
from agent_lifecycle.contracts.adapter_session_schemas import ADAPTER_SESSION_SCHEMAS
from agent_lifecycle.contracts.adapter_task_schemas import ADAPTER_TASK_SCHEMAS
from agent_lifecycle.contracts.audit_schemas import AUDIT_SCHEMAS
from agent_lifecycle.contracts.bug_forensics_schemas import BUG_FORENSICS_SCHEMAS
from agent_lifecycle.contracts.context_model_schemas import CONTEXT_MODEL_SCHEMAS
from agent_lifecycle.contracts.core_schemas import CORE_SCHEMAS
from agent_lifecycle.contracts.cross_check_schemas import CROSS_CHECK_SCHEMAS
from agent_lifecycle.contracts.evidence_import_schemas import EVIDENCE_IMPORT_SCHEMAS
from agent_lifecycle.contracts.host_capability_schemas import HOST_CAPABILITY_SCHEMAS
from agent_lifecycle.contracts.import_dialect_schemas import IMPORT_DIALECT_SCHEMAS
from agent_lifecycle.contracts.metric_schemas import METRIC_SCHEMAS
from agent_lifecycle.contracts.plan_contract_schemas import PLAN_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.policy_schemas import POLICY_SCHEMAS
from agent_lifecycle.contracts.proof_integrity_schemas import PROOF_INTEGRITY_SCHEMAS
from agent_lifecycle.contracts.progress_bridge_schemas import PROGRESS_BRIDGE_SCHEMAS
from agent_lifecycle.contracts.progress_hook_schemas import PROGRESS_HOOK_SCHEMAS
from agent_lifecycle.contracts.release_contract_schemas import RELEASE_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_SCHEMAS
from agent_lifecycle.contracts.review_mesh_recommendation_schemas import REVIEW_MESH_RECOMMENDATION_SCHEMAS
from agent_lifecycle.contracts.review_quality_schemas import REVIEW_QUALITY_SCHEMAS
from agent_lifecycle.contracts.runner_schemas import RUNNER_SCHEMAS
from agent_lifecycle.contracts.runner_worktree_schemas import RUNNER_WORKTREE_SCHEMAS
from agent_lifecycle.contracts.sandbox_schemas import SANDBOX_SCHEMAS
from agent_lifecycle.contracts.status_goal_schemas import STATUS_GOAL_SCHEMAS
from agent_lifecycle.contracts.task_template_schemas import TASK_TEMPLATE_SCHEMAS
from agent_lifecycle.contracts.usage_export_schemas import USAGE_EXPORT_SCHEMAS
from agent_lifecycle.contracts.schema_builders import open_object_schema

SCHEMA_INDEX_VERSION = "agent-lifecycle-schema-index.v1"

LIFECYCLE_START_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-lifecycle-start-receipt.v1": open_object_schema(
        "agent-lifecycle-start-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "requestedMode",
            "action",
            "input",
            "delegate",
            "executionStarted",
            "lifecycleCoverageClaimed",
            "requiresReview",
            "modelCallsStarted",
            "hostLaunchStarted",
            "nativeSessionAttached",
            "rawTaskTextStored",
            "secretsWritten",
            "nativeConfigWritten",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["REVIEW_REQUIRED", "READY", "PASS", "UNMANAGED", "BLOCKED"]},
            "adapterId": {"type": "string", "minLength": 1},
            "requestedMode": {"enum": ["auto", "research", "plan", "review", "implement"]},
            "action": {"enum": ["DRAFT_INTAKE", "DRAFT_PLAN_REVIEW", "MANAGED_RUN", "RESUME", "BLOCKED"]},
            "input": {"type": "object"},
            "delegate": {"type": ["object", "null"]},
            "executionStarted": {"type": "boolean"},
            "lifecycleCoverageClaimed": {"type": "boolean"},
            "requiresReview": {"type": "boolean"},
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"type": "boolean"},
            "launchReceipt": {"type": ["object", "null"]},
            "nativeSessionAttached": {"const": False},
            "rawTaskTextStored": {"const": False},
            "secretsWritten": {"const": False},
            "nativeConfigWritten": {"const": False},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-local-host-launch-profile.v1": open_object_schema(
        "agent-local-host-launch-profile.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "executable",
            "argvTemplate",
            "versionProbeArgs",
            "env",
            "timeoutSeconds",
            "shell",
            "writesNativeConfig",
            "promptInjectionDefault",
            "publicSupportClaimed",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"const": "LOCAL_OPT_IN"},
            "adapterId": {"type": "string", "minLength": 1},
            "executable": {"type": "string", "minLength": 1},
            "argvTemplate": {"type": "array", "items": {"type": "string"}},
            "versionProbeArgs": {
                "oneOf": [
                    {"const": ["--version"]},
                    {"const": ["-V"]},
                    {"const": ["version"]},
                ]
            },
            "env": {
                "type": "object",
                "required": ["allow", "allowPatterns", "projectPolicyAllowed"],
                "properties": {
                    "allow": {"type": "array", "items": {"type": "string"}},
                    "allowPatterns": {"const": []},
                    "projectPolicyAllowed": {"const": False},
                },
            },
            "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 300},
            "shell": {"const": False},
            "writesNativeConfig": {"const": False},
            "promptInjectionDefault": {"const": False},
            "publicSupportClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-local-host-launch-profile-validation.v1": open_object_schema(
        "agent-local-host-launch-profile-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "profileDigest",
            "adapterId",
            "allowedPlaceholders",
            "blockers",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "adapterId": {"type": ["string", "null"]},
            "allowedPlaceholders": {"type": "array", "items": {"type": "string"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-local-host-launch-profile-receipt.v1": open_object_schema(
        "agent-local-host-launch-profile-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "operation",
            "profilePath",
            "profile",
            "profileDigest",
            "processCalls",
            "probeReceipt",
            "redactionApplied",
            "hostLaunchStarted",
            "modelCallsStarted",
            "secretsWritten",
            "nativeConfigWritten",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL", "BLOCKED"]},
            "operation": {"enum": ["INSPECT", "PREFLIGHT"]},
            "profilePath": {"type": "string", "minLength": 1},
            "profile": {"type": "object"},
            "profileDigest": {"type": ["string", "null"]},
            "processCalls": {"type": "integer", "minimum": 0, "maximum": 1},
            "probeReceipt": {"type": ["object", "null"]},
            "redactionApplied": {"type": "boolean"},
            "hostLaunchStarted": {"type": "boolean"},
            "modelCallsStarted": {"const": False},
            "secretsWritten": {"const": False},
            "nativeConfigWritten": {"const": False},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-local-host-launch-probe-receipt.v1": open_object_schema(
        "agent-local-host-launch-probe-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "argv",
            "argvRedacted",
            "shell",
            "timeoutSeconds",
            "env",
            "exitCode",
            "timedOut",
            "stdout",
            "stderr",
            "hostLaunchStarted",
            "modelCallsStarted",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "argv": {"type": "array", "items": {"type": "string"}},
            "argvRedacted": {"type": "boolean"},
            "shell": {"const": False},
            "timeoutSeconds": {"type": "number"},
            "env": {"type": "object"},
            "exitCode": {"type": ["integer", "null"]},
            "timedOut": {"type": "boolean"},
            "stdout": {"type": "object"},
            "stderr": {"type": "object"},
            "hostLaunchStarted": {"const": True},
            "modelCallsStarted": {"const": False},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}

RISK_EXECUTION_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-risk-execution-policy.v1": open_object_schema(
        "agent-risk-execution-policy.v1",
        required=["schemaVersion", "tiers", "productionPromotionClaimed"],
        properties={
            "tiers": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-risk-execution-profile.v1": open_object_schema(
        "agent-risk-execution-profile.v1",
        required=[
            "schemaVersion",
            "status",
            "requestedRisk",
            "planRiskTier",
            "resolvedRiskTier",
            "adapterId",
            "operationId",
            "runId",
            "packageId",
            "planRevision",
            "planDigest",
            "taskId",
            "sourceRevision",
            "qualityFloorDecision",
            "modelRoute",
            "resourceCaps",
            "usageEvidence",
            "policyDigest",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "profileDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "BLOCKED"]},
            "requestedRisk": {"enum": ["auto", "S0", "S1", "S2"]},
            "planRiskTier": {"enum": ["S0", "S1", "S2"]},
            "resolvedRiskTier": {"enum": ["S0", "S1", "S2"]},
            "adapterId": {"type": "string", "minLength": 1},
            "operationId": {"type": "string", "minLength": 1},
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": "string", "minLength": 1},
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "taskId": {"type": "string", "minLength": 1},
            "sourceRevision": {"type": "string", "minLength": 1},
            "qualityFloorDecision": {"type": "object"},
            "modelRoute": {"type": "object"},
            "resourceCaps": {"type": "object"},
            "usageEvidence": {"type": "object"},
            "policyDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}

_SCHEMA_GROUPS = (
    CORE_SCHEMAS,
    AUDIT_SCHEMAS,
    ADAPTER_SESSION_SCHEMAS,
    ADAPTER_TASK_SCHEMAS,
    ADAPTER_EVENT_SCHEMAS,
    REVIEW_QUALITY_SCHEMAS,
    EVIDENCE_IMPORT_SCHEMAS,
    IMPORT_DIALECT_SCHEMAS,
    STATUS_GOAL_SCHEMAS,
    TASK_TEMPLATE_SCHEMAS,
    RUNNER_SCHEMAS,
    RUNNER_WORKTREE_SCHEMAS,
    BUG_FORENSICS_SCHEMAS,
    CROSS_CHECK_SCHEMAS,
    REVIEW_MESH_SCHEMAS,
    REVIEW_MESH_RECOMMENDATION_SCHEMAS,
    SANDBOX_SCHEMAS,
    HOST_CAPABILITY_SCHEMAS,
    USAGE_EXPORT_SCHEMAS,
    PROOF_INTEGRITY_SCHEMAS,
    PROGRESS_BRIDGE_SCHEMAS,
    PROGRESS_HOOK_SCHEMAS,
    ADAPTER_CONTRACT_SCHEMAS,
    CONTEXT_MODEL_SCHEMAS,
    RELEASE_CONTRACT_SCHEMAS,
    PLAN_CONTRACT_SCHEMAS,
    METRIC_SCHEMAS,
    POLICY_SCHEMAS,
    LIFECYCLE_START_SCHEMAS,
    RISK_EXECUTION_SCHEMAS,
)

_SCHEMAS: dict[str, dict[str, Any]] = {}
for _group in _SCHEMA_GROUPS:
    _overlap = set(_SCHEMAS).intersection(_group)
    if _overlap:
        raise RuntimeError(f"duplicate schema ids: {sorted(_overlap)}")
    _SCHEMAS.update(_group)


def list_schemas() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_INDEX_VERSION,
        "schemas": [
            {"id": schema_id, "draft": schema["$schema"]}
            for schema_id, schema in sorted(_SCHEMAS.items())
        ],
    }


def get_schema(schema_id: str) -> dict[str, Any]:
    if schema_id not in _SCHEMAS:
        from agent_lifecycle.contracts.errors import LifecycleError

        raise LifecycleError("unknown-schema", f"unknown schema: {schema_id}")
    return deepcopy(_SCHEMAS[schema_id])
