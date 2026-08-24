"""Built-in JSON schema registry for portable lifecycle envelopes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts.adapter_contract_schemas import ADAPTER_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.adapter_event_schemas import ADAPTER_EVENT_SCHEMAS
from agent_lifecycle.contracts.adapter_session_schemas import ADAPTER_SESSION_SCHEMAS
from agent_lifecycle.contracts.adapter_task_schemas import ADAPTER_TASK_SCHEMAS
from agent_lifecycle.contracts.audit_optimization_schemas import (
    AUDIT_OPTIMIZATION_SCHEMAS,
)
from agent_lifecycle.contracts.audit_schemas import AUDIT_SCHEMAS
from agent_lifecycle.contracts.benchmark_schemas import BENCHMARK_SCHEMAS
from agent_lifecycle.contracts.bug_forensics_schemas import BUG_FORENSICS_SCHEMAS
from agent_lifecycle.contracts.context_checkpoint_schemas import (
    CONTEXT_CHECKPOINT_SCHEMAS,
)
from agent_lifecycle.contracts.context_model_schemas import CONTEXT_MODEL_SCHEMAS
from agent_lifecycle.contracts.core_schemas import CORE_SCHEMAS
from agent_lifecycle.contracts.cross_check_schemas import CROSS_CHECK_SCHEMAS
from agent_lifecycle.contracts.evidence_import_schemas import EVIDENCE_IMPORT_SCHEMAS
from agent_lifecycle.contracts.execution_strategy_schemas import (
    EXECUTION_STRATEGY_SCHEMAS,
)
from agent_lifecycle.contracts.host_capability_schemas import HOST_CAPABILITY_SCHEMAS
from agent_lifecycle.contracts.import_dialect_schemas import IMPORT_DIALECT_SCHEMAS
from agent_lifecycle.contracts.lifecycle_control_definitions import (
    CONTROL_EVENT_TYPES,
    CONTROL_LEVELS,
    CONTROL_OPERATIONS,
    CONTROL_STATUSES,
    LIFECYCLE_CONTROL_ATTESTATION_SCHEMA,
    LIFECYCLE_CONTROL_DECISION_SCHEMA,
    LIFECYCLE_CONTROL_EVENT_SCHEMA,
    LIFECYCLE_CONTROL_POLICY_SCHEMA,
    LIFECYCLE_CONTROL_POLICY_VALIDATION_SCHEMA,
    LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA,
    LIFECYCLE_CONTROL_QUALIFICATION_VALIDATION_SCHEMA,
    LIFECYCLE_CONTROL_REQUEST_SCHEMA,
    MAX_CONTROL_STRING_LENGTH,
    QUALIFICATION_STATUSES,
)
from agent_lifecycle.contracts.metric_schemas import METRIC_SCHEMAS
from agent_lifecycle.contracts.plan_contract_schemas import PLAN_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.plan_delta_schemas import PLAN_DELTA_SCHEMAS
from agent_lifecycle.contracts.plan_manifest_schemas import PLAN_MANIFEST_SCHEMAS
from agent_lifecycle.contracts.planning_launch_schemas import PLANNING_LAUNCH_SCHEMAS
from agent_lifecycle.contracts.policy_schemas import POLICY_SCHEMAS
from agent_lifecycle.contracts.progress_bridge_schemas import PROGRESS_BRIDGE_SCHEMAS
from agent_lifecycle.contracts.progress_hook_schemas import PROGRESS_HOOK_SCHEMAS
from agent_lifecycle.contracts.project_profile_preset_schemas import (
    PROJECT_PROFILE_PRESET_SCHEMAS,
)
from agent_lifecycle.contracts.project_profile_schemas import PROJECT_PROFILE_SCHEMAS
from agent_lifecycle.contracts.proof_integrity_schemas import PROOF_INTEGRITY_SCHEMAS
from agent_lifecycle.contracts.public_locators import PUBLIC_LOCATOR_SCHEMAS
from agent_lifecycle.contracts.release_contract_schemas import RELEASE_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.research_evidence_schemas import (
    RESEARCH_EVIDENCE_SCHEMAS,
)
from agent_lifecycle.contracts.review_mesh_recommendation_schemas import (
    REVIEW_MESH_RECOMMENDATION_SCHEMAS,
)
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_SCHEMAS
from agent_lifecycle.contracts.review_quality_schemas import REVIEW_QUALITY_SCHEMAS
from agent_lifecycle.contracts.runner_schemas import RUNNER_SCHEMAS
from agent_lifecycle.contracts.runner_worktree_schemas import RUNNER_WORKTREE_SCHEMAS
from agent_lifecycle.contracts.sandbox_schemas import SANDBOX_SCHEMAS
from agent_lifecycle.contracts.schema_builders import open_object_schema
from agent_lifecycle.contracts.status_goal_schemas import STATUS_GOAL_SCHEMAS
from agent_lifecycle.contracts.task_template_schemas import TASK_TEMPLATE_SCHEMAS
from agent_lifecycle.contracts.thread_bridge_schemas import THREAD_BRIDGE_SCHEMAS
from agent_lifecycle.contracts.usage_export_schemas import USAGE_EXPORT_SCHEMAS
from agent_lifecycle.contracts.workflow_artifact_schemas import WORKFLOW_ARTIFACT_SCHEMAS
from agent_lifecycle.contracts.workflow_authorization_schemas import WORKFLOW_AUTHORIZATION_SCHEMAS
from agent_lifecycle.contracts.workflow_state_schemas import WORKFLOW_STATE_SCHEMAS

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
            "executionStrategy": {"type": ["object", "null"]},
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
            "qualification": {"type": "object"},
        },
    ),
    "agent-host-launch-qualification-policy.v1": open_object_schema(
        "agent-host-launch-qualification-policy.v1",
        required=[
            "schemaVersion",
            "expectedVersion",
            "receiptFile",
            "requiredForManagedTask",
            "maxPreflightProcesses",
            "modelCallsForPreflight",
        ],
        properties={
            "expectedVersion": {"type": "string", "minLength": 5},
            "receiptFile": {"type": "string", "minLength": 6},
            "requiredForManagedTask": {"const": True},
            "maxPreflightProcesses": {"const": 1},
            "modelCallsForPreflight": {"const": 0},
        },
    ),
    "agent-host-launch-qualification-receipt.v1": open_object_schema(
        "agent-host-launch-qualification-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "expectedHostVersion",
            "actualHostVersion",
            "profileDigest",
            "probeReceiptDigest",
            "processCalls",
            "modelCallsStarted",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterId": {"type": "string", "minLength": 1},
            "expectedHostVersion": {"type": "string", "minLength": 5},
            "actualHostVersion": {"type": ["string", "null"]},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "executableIdentity": {"type": ["object", "null"]},
            "probeReceiptDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "processCalls": {"const": 1},
            "modelCallsStarted": {"const": False},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-qualified-launch-profile-generation.v1": open_object_schema(
        "agent-qualified-launch-profile-generation.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "profilePath",
            "profileDigest",
            "publicSupportClaimed",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"const": "PASS"},
            "adapterId": {"type": "string", "minLength": 1},
            "profilePath": {"type": "string", "minLength": 1},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "profileOrigin": {"enum": ["SHIPPED_PROFILE_BOUND", "OPERATOR_OWNED_UNVERIFIED"]},
            "shippedProfileDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
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
            "hostIdentity": {"type": ["object", "null"]},
            "processCalls": {"type": "integer", "minimum": 0, "maximum": 1},
            "probeReceipt": {"type": ["object", "null"]},
            "qualificationReceipt": {"type": ["object", "null"]},
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

PLAN_INTEGRITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-plan-file-inventory.v1": open_object_schema(
        "agent-plan-file-inventory.v1",
        required=["schemaVersion", "entries"],
        properties={
            "schemaVersion": {"const": "agent-plan-file-inventory.v1"},
            "entries": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-plan-lock.v2": open_object_schema(
        "agent-plan-lock.v2",
        required=["schemaVersion", "packageId", "planRevision", "manifestHash", "planFilesHash", "entries"],
        properties={
            "schemaVersion": {"const": "agent-plan-lock.v2"},
            "packageId": {"type": "string", "minLength": 1},
            "planRevision": {"type": "integer", "minimum": 1},
            "manifestHash": {"type": "string", "minLength": 64, "maxLength": 64},
            "planFilesHash": {"type": "string", "minLength": 64, "maxLength": 64},
            "entries": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        },
    ),
    "agent-plan-package-integrity-verification.v1": open_object_schema(
        "agent-plan-package-integrity-verification.v1",
        required=[
            "schemaVersion",
            "status",
            "required",
            "lockSchemaVersion",
            "filesystemVerified",
            "blockers",
            "verificationDigest",
        ],
        properties={
            "schemaVersion": {"const": "agent-plan-package-integrity-verification.v1"},
            "status": {"enum": ["PASS", "FAIL"]},
            "required": {"type": "boolean"},
            "lockSchemaVersion": {"enum": ["agent-plan-lock.v1", "agent-plan-lock.v2"]},
            "filesystemVerified": {"type": "boolean"},
            "manifestHash": {"type": "string", "minLength": 64, "maxLength": 64},
            "planFilesHash": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "entries": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "verificationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
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


def _closed_schema(schema_id: str, required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    schema = open_object_schema(schema_id, required=required, properties=properties)
    schema["additionalProperties"] = False
    return schema


def _required(*fields: str) -> list[str]:
    return ["schemaVersion", *fields]


_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 64}
_PATHS = {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 64}


def _strings(*fields: str, max_length: int = 128) -> dict[str, dict[str, Any]]:
    return {field: {"type": "string", "minLength": 1, "maxLength": max_length} for field in fields}


_LIFECYCLE_CONTROL_SCHEMAS: dict[str, dict[str, Any]] = {
    LIFECYCLE_CONTROL_POLICY_SCHEMA: _closed_schema(
        LIFECYCLE_CONTROL_POLICY_SCHEMA,
        _required(
            "policyId",
            "revision",
            "defaultLevel",
            "operations",
            "limits",
            "authority",
            "productionPromotionClaimed",
            "policyDigest",
        ),
        {
            "policyId": {"type": "string", "minLength": 1, "maxLength": MAX_CONTROL_STRING_LENGTH},
            "revision": {"type": "integer", "minimum": 1},
            "defaultLevel": {"enum": list(CONTROL_LEVELS)},
            "operations": {"type": "object"},
            "limits": {"type": "object"},
            "authority": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
            "policyDigest": _DIGEST,
        },
    ),
    LIFECYCLE_CONTROL_POLICY_VALIDATION_SCHEMA: open_object_schema(
        LIFECYCLE_CONTROL_POLICY_VALIDATION_SCHEMA,
        required=_required("status", "policyId", "blockers", "productionPromotionClaimed", "validationDigest"),
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "policyId": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    LIFECYCLE_CONTROL_REQUEST_SCHEMA: _closed_schema(
        LIFECYCLE_CONTROL_REQUEST_SCHEMA,
        _required(
            "requestId",
            "adapterId",
            "host",
            "hostVersion",
            "operation",
            "runId",
            "taskId",
            "packageId",
            "planRevision",
            "planDigest",
            "lockDigest",
            "stateRevision",
            "actionDigest",
            "paths",
            "requestedLevel",
            "producerId",
            "nonce",
            "createdAt",
            "productionPromotionClaimed",
            "requestDigest",
        ),
        {
            **_strings("requestId", "adapterId", "host", "hostVersion", "runId", "taskId", "packageId", "producerId"),
            "operation": {"enum": list(CONTROL_OPERATIONS)},
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "lockDigest": _DIGEST,
            "stateRevision": {"type": "integer", "minimum": 1},
            "actionDigest": _DIGEST,
            "paths": _PATHS,
            "requestedLevel": {"enum": list(CONTROL_LEVELS)},
            "nonce": {"type": "string", "minLength": 16, "maxLength": 128},
            "createdAt": {"type": "string", "minLength": 1, "maxLength": 64},
            "productionPromotionClaimed": {"const": False},
            "requestDigest": _DIGEST,
        },
    ),
    LIFECYCLE_CONTROL_DECISION_SCHEMA: _closed_schema(
        LIFECYCLE_CONTROL_DECISION_SCHEMA,
        _required(
            "status",
            "requestDigest",
            "operation",
            "effectiveLevel",
            "hostActionAllowed",
            "authority",
            "blockers",
            "productionPromotionClaimed",
            "decisionDigest",
        ),
        {
            "status": {"enum": list(CONTROL_STATUSES)},
            "requestDigest": _DIGEST,
            "operation": {"enum": list(CONTROL_OPERATIONS)},
            "effectiveLevel": {"enum": list(CONTROL_LEVELS)},
            "hostActionAllowed": {"type": "boolean"},
            "authority": {"enum": ["frozen-plan-and-state", "guidance-only", "none"]},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "decisionDigest": _DIGEST,
        },
    ),
    LIFECYCLE_CONTROL_EVENT_SCHEMA: _closed_schema(
        LIFECYCLE_CONTROL_EVENT_SCHEMA,
        _required(
            "eventId",
            "eventType",
            "status",
            "requestDigest",
            "operation",
            "producer",
            "nonce",
            "changedPaths",
            "outcome",
            "recordedAt",
            "productionPromotionClaimed",
            "eventDigest",
        ),
        {
            "eventId": {"type": "string", "minLength": 1, "maxLength": 128},
            "eventType": {"enum": list(CONTROL_EVENT_TYPES)},
            "status": {"enum": list(CONTROL_STATUSES)},
            "requestDigest": _DIGEST,
            "operation": {"enum": list(CONTROL_OPERATIONS)},
            "producer": {"type": "object"},
            "nonce": {"type": "string", "minLength": 16, "maxLength": 128},
            "changedPaths": _PATHS,
            "outcome": {"type": "object"},
            "recordedAt": {"type": "string", "minLength": 1, "maxLength": 64},
            "productionPromotionClaimed": {"const": False},
            "eventDigest": _DIGEST,
        },
    ),
    LIFECYCLE_CONTROL_ATTESTATION_SCHEMA: _closed_schema(
        LIFECYCLE_CONTROL_ATTESTATION_SCHEMA,
        _required(
            "attestationId",
            "domain",
            "producerId",
            "adapterId",
            "hostVersion",
            "operation",
            "nonce",
            "issuedAt",
            "expiresAt",
            "planDigest",
            "lockDigest",
            "stateRevision",
            "actionDigest",
            "outcomeDigest",
            "keyId",
            "signature",
            "productionPromotionClaimed",
            "attestationDigest",
        ),
        {
            **_strings("attestationId", "producerId", "adapterId", "hostVersion", "keyId"),
            "domain": {"const": LIFECYCLE_CONTROL_ATTESTATION_SCHEMA},
            "operation": {"enum": list(CONTROL_OPERATIONS)},
            "nonce": {"type": "string", "minLength": 16, "maxLength": 128},
            "issuedAt": {"type": "string", "minLength": 1, "maxLength": 64},
            "expiresAt": {"type": "string", "minLength": 1, "maxLength": 64},
            "planDigest": _DIGEST,
            "lockDigest": _DIGEST,
            "stateRevision": {"type": "integer", "minimum": 1},
            "actionDigest": _DIGEST,
            "outcomeDigest": _DIGEST,
            "signature": {"type": "string", "minLength": 1, "maxLength": 2048},
            "productionPromotionClaimed": {"const": False},
            "attestationDigest": _DIGEST,
        },
    ),
    LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA: _closed_schema(
        LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA,
        _required(
            "status",
            "adapterId",
            "host",
            "hostVersion",
            "operation",
            "declaredLevel",
            "supportedLevel",
            "qualifiedLevel",
            "positiveEvidence",
            "negativeEvidence",
            "evidenceRefs",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ),
        {
            "status": {"enum": list(QUALIFICATION_STATUSES)},
            **_strings("adapterId", "host", "hostVersion", max_length=MAX_CONTROL_STRING_LENGTH),
            "operation": {"enum": list(CONTROL_OPERATIONS)},
            "declaredLevel": {"enum": list(CONTROL_LEVELS)},
            "supportedLevel": {"enum": list(CONTROL_LEVELS)},
            "qualifiedLevel": {"enum": list(CONTROL_LEVELS)},
            "positiveEvidence": {"type": "array", "items": {"type": "object"}, "maxItems": 64},
            "negativeEvidence": {"type": "array", "items": {"type": "object"}, "maxItems": 64},
            "evidenceRefs": {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 64},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    LIFECYCLE_CONTROL_QUALIFICATION_VALIDATION_SCHEMA: open_object_schema(
        LIFECYCLE_CONTROL_QUALIFICATION_VALIDATION_SCHEMA,
        required=_required(
            "status", "qualificationStatus", "blockers", "productionPromotionClaimed", "validationDigest"
        ),
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "qualificationStatus": {"enum": list(QUALIFICATION_STATUSES)},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}

_SCHEMA_GROUPS = (
    CORE_SCHEMAS,
    AUDIT_SCHEMAS,
    AUDIT_OPTIMIZATION_SCHEMAS,
    BENCHMARK_SCHEMAS,
    ADAPTER_SESSION_SCHEMAS,
    ADAPTER_TASK_SCHEMAS,
    ADAPTER_EVENT_SCHEMAS,
    REVIEW_QUALITY_SCHEMAS,
    EVIDENCE_IMPORT_SCHEMAS,
    EXECUTION_STRATEGY_SCHEMAS,
    IMPORT_DIALECT_SCHEMAS,
    STATUS_GOAL_SCHEMAS,
    TASK_TEMPLATE_SCHEMAS,
    THREAD_BRIDGE_SCHEMAS,
    RUNNER_SCHEMAS,
    RUNNER_WORKTREE_SCHEMAS,
    WORKFLOW_ARTIFACT_SCHEMAS,
    WORKFLOW_AUTHORIZATION_SCHEMAS,
    WORKFLOW_STATE_SCHEMAS,
    BUG_FORENSICS_SCHEMAS,
    CROSS_CHECK_SCHEMAS,
    REVIEW_MESH_SCHEMAS,
    REVIEW_MESH_RECOMMENDATION_SCHEMAS,
    SANDBOX_SCHEMAS,
    HOST_CAPABILITY_SCHEMAS,
    _LIFECYCLE_CONTROL_SCHEMAS,
    USAGE_EXPORT_SCHEMAS,
    PROOF_INTEGRITY_SCHEMAS,
    RESEARCH_EVIDENCE_SCHEMAS,
    PROGRESS_BRIDGE_SCHEMAS,
    PROGRESS_HOOK_SCHEMAS,
    PUBLIC_LOCATOR_SCHEMAS,
    PROJECT_PROFILE_SCHEMAS,
    PROJECT_PROFILE_PRESET_SCHEMAS,
    ADAPTER_CONTRACT_SCHEMAS,
    CONTEXT_MODEL_SCHEMAS,
    CONTEXT_CHECKPOINT_SCHEMAS,
    RELEASE_CONTRACT_SCHEMAS,
    PLAN_CONTRACT_SCHEMAS,
    PLAN_MANIFEST_SCHEMAS,
    PLAN_DELTA_SCHEMAS,
    PLANNING_LAUNCH_SCHEMAS,
    METRIC_SCHEMAS,
    POLICY_SCHEMAS,
    LIFECYCLE_START_SCHEMAS,
    RISK_EXECUTION_SCHEMAS,
    PLAN_INTEGRITY_SCHEMAS,
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
        "schemas": [{"id": schema_id, "draft": schema["$schema"]} for schema_id, schema in sorted(_SCHEMAS.items())],
    }


def get_schema(schema_id: str) -> dict[str, Any]:
    if schema_id not in _SCHEMAS:
        from agent_lifecycle.contracts.errors import LifecycleError

        raise LifecycleError("unknown-schema", f"unknown schema: {schema_id}")
    return deepcopy(_SCHEMAS[schema_id])
