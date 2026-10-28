"""Contracts and runtime validation for durable workflow state."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.closing_time import closing_instant as _closing_instant
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.immutable_input_schemas import _validate_a5_state
from agent_lifecycle.contracts.paths import MAX_REPO_PATH_BYTES, normalize_repo_path
from agent_lifecycle.contracts.schema_builders import open_object_schema
from agent_lifecycle.contracts.workflow_storage_schemas import (
    WORKFLOW_STATE_V5,
    validate_storage_counts,
    validate_storage_metadata,
)

WORKFLOW_STATE_V3 = "agent-workflow-state.v3"
WORKFLOW_STATE_V4 = "agent-workflow-state.v4"
WORKFLOW_STATE_MIGRATION_RECEIPT = "agent-workflow-state-migration-receipt.v1"
CLOSING_CONTEXT_V1 = "agent-closing-context.v1"
RUNTIME_BINDING_V1 = "agent-workflow-journal-binding.v1"
ADOPTION_INPUT_V1 = "agent-workflow-adoption-input.v1"
ADOPTION_SELECTION_V1 = "agent-workflow-adoption-selection.v1"
TRANSITION_REQUEST_V1 = "agent-workflow-transition-request.v1"
COMMITTED_RESULT_V1 = "agent-workflow-committed-result.v1"
PROJECTION_STATUS_V1 = "agent-workflow-projection-status.v1"

_TRANSITION_FIELDS = frozenset(
    {
        "schemaVersion",
        "binding",
        "operationId",
        "requestDigest",
        "expectedWorkflowRevision",
        "expectedAccountingRevisions",
        "action",
        "eventType",
        "nextStateRef",
        "eventBundleRef",
        "semanticResultRef",
        "authorityContextRef",
        "activationEffect",
        "preparedProofInputRef",
    }
)
_ACTIVATION_EFFECT_FIELDS = frozenset(
    {
        "closingWindowId",
        "authorityDomain",
        "issuerId",
        "issuerGeneration",
        "nonce",
        "commitBoundAuthorityRef",
        "qualifiedPolicyEffectRef",
        "windowRequestRef",
    }
)
_COMMITTED_RESULT_FIELDS = frozenset(
    {
        "schemaVersion",
        "runId",
        "operationId",
        "requestDigest",
        "beforeRevision",
        "afterRevision",
        "stateDigest",
        "eventBundleDigest",
        "semanticResultRef",
        "closingWindowId",
        "policyEventId",
        "projectionGeneration",
        "resultDigest",
        "authorityDecisionRef",
        "resourcePolicyEffectRef",
        "deadlineDecisionRef",
        "clockObservationRef",
        "committedProofEnvelopeRef",
    }
)
_PROJECTION_STATUS_FIELDS = frozenset(
    {
        "schemaVersion",
        "runId",
        "workflowRevision",
        "generation",
        "stateDigest",
        "eventBundleDigest",
        "status",
        "ackRef",
        "committedProofEnvelopeRef",
    }
)

_ADOPTION_INPUT_FIELDS = frozenset(
    {
        "schemaVersion",
        "operationId",
        "bindingRef",
        "legacyStateRef",
        "legacyEventLogRef",
        "initialSnapshotRef",
        "accountingMode",
    }
)
_ADOPTION_SELECTION_FIELDS = frozenset(
    {
        "schemaVersion",
        "expectedBindingDigest",
        "expectedPinDigest",
        "expectedInitialSnapshotDigest",
        "expectedAccountingStateDigest",
        "expectedAccountingRevision",
        "expectedJournalIdentity",
        "expectedBudgetScopeId",
        "expectedStorageProtocolVersion",
        "expectedWorkflowProtocolVersion",
        "operatorQualificationRef",
        "quiescenceEvidenceRef",
        "writerInventoryRef",
    }
)
_ADOPTION_REF_FIELDS = frozenset({"path", "sha256", "bytes"})


def _validate_adoption_ref(value: Any, label: str) -> None:
    if type(value) is not dict or set(value) != _ADOPTION_REF_FIELDS:
        raise LifecycleError("workflow-adoption-invalid", f"Invalid {label}")
    if type(value["path"]) is not str or not 1 <= len(value["path"]) <= 4096:
        raise LifecycleError("workflow-adoption-invalid", f"Invalid {label} path")
    if type(value["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None:
        raise LifecycleError("workflow-adoption-invalid", f"Invalid {label} digest")
    if type(value["bytes"]) is not int or not 0 <= value["bytes"] <= 8_388_608:
        raise LifecycleError("workflow-adoption-invalid", f"Invalid {label} size")


def validate_adoption_input(value: Any) -> dict[str, Any]:
    """Validate closed adoption data shape; this never qualifies its caller."""
    if type(value) is not dict or set(value) != _ADOPTION_INPUT_FIELDS:
        raise LifecycleError("workflow-adoption-invalid", "AdoptionInput has missing or unknown fields")
    if value["schemaVersion"] != ADOPTION_INPUT_V1 or value["accountingMode"] != "EXISTING_QUALIFIED_SCOPE":
        raise LifecycleError("workflow-adoption-invalid", "Unsupported adoption input mode")
    if type(value["operationId"]) is not str or not 1 <= len(value["operationId"]) <= 256:
        raise LifecycleError("workflow-adoption-invalid", "Invalid adoption operationId")
    for name in ("bindingRef", "legacyStateRef", "initialSnapshotRef"):
        _validate_adoption_ref(value[name], name)
    if value["legacyEventLogRef"] is not None:
        _validate_adoption_ref(value["legacyEventLogRef"], "legacyEventLogRef")
    return value


def validate_adoption_selection(value: Any) -> dict[str, Any]:
    """Validate selected bytes only; operator provenance remains a separate gate."""
    if type(value) is not dict or set(value) != _ADOPTION_SELECTION_FIELDS:
        raise LifecycleError("workflow-adoption-invalid", "AdoptionSelection has missing or unknown fields")
    if value["schemaVersion"] != ADOPTION_SELECTION_V1:
        raise LifecycleError("workflow-adoption-invalid", "Unsupported adoption selection")
    for name in (
        "expectedBindingDigest",
        "expectedPinDigest",
        "expectedInitialSnapshotDigest",
        "expectedAccountingStateDigest",
    ):
        item = value[name]
        if type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None:
            raise LifecycleError("workflow-adoption-invalid", f"Invalid {name}")
    for name in ("expectedJournalIdentity", "expectedBudgetScopeId"):
        item = value[name]
        if type(item) is not str or not 1 <= len(item) <= 256:
            raise LifecycleError("workflow-adoption-invalid", f"Invalid {name}")
    revision = value["expectedAccountingRevision"]
    if type(revision) is not int or not 0 <= revision <= 9_007_199_254_740_991:
        raise LifecycleError("workflow-adoption-invalid", "Invalid expectedAccountingRevision")
    if value["expectedStorageProtocolVersion"] != "5" or value["expectedWorkflowProtocolVersion"] != "1":
        raise LifecycleError("workflow-adoption-invalid", "Unsupported adoption protocol")
    for name in ("operatorQualificationRef", "quiescenceEvidenceRef", "writerInventoryRef"):
        _validate_adoption_ref(value[name], name)
    return value


def validate_transition_request(value: Any) -> dict[str, Any]:
    """Validate closed transition wire data without granting a native transition."""

    def invalid(detail: str) -> None:
        raise LifecycleError("workflow-transition-invalid", detail)

    def text(item: Any, label: str, limit: int = 256) -> None:
        if type(item) is not str or not 1 <= len(item) <= limit:
            invalid(f"Invalid {label}")

    def digest(item: Any, label: str) -> None:
        if type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None:
            invalid(f"Invalid {label}")

    def artifact(item: Any, label: str) -> None:
        try:
            _validate_adoption_ref(item, label)
        except LifecycleError:
            invalid(f"Invalid {label}")

    if type(value) is not dict or set(value) != _TRANSITION_FIELDS:
        invalid("TransitionRequest has missing or unknown fields")
    if value["schemaVersion"] != TRANSITION_REQUEST_V1:
        invalid("Unsupported transition request")
    binding = value["binding"]
    if type(binding) is not dict or set(binding) != {"bindingId", "expectedBindingDigest"}:
        invalid("Invalid transition binding")
    text(binding["bindingId"], "bindingId")
    digest(binding["expectedBindingDigest"], "expectedBindingDigest")
    text(value["operationId"], "operationId")
    digest(value["requestDigest"], "requestDigest")
    revision = value["expectedWorkflowRevision"]
    if type(revision) is not int or not 0 <= revision <= 9_007_199_254_740_991:
        invalid("Invalid expectedWorkflowRevision")
    accounting = value["expectedAccountingRevisions"]
    if type(accounting) is not list or len(accounting) > 64:
        invalid("Invalid expectedAccountingRevisions")
    scopes: set[str] = set()
    for item in accounting:
        if type(item) is not dict or set(item) != {"budgetScopeId", "revision"}:
            invalid("Invalid accounting revision")
        text(item["budgetScopeId"], "budgetScopeId")
        if item["budgetScopeId"] in scopes:
            invalid("Duplicate accounting scope")
        scopes.add(item["budgetScopeId"])
        if type(item["revision"]) is not int or not 0 <= item["revision"] <= 9_007_199_254_740_991:
            invalid("Invalid accounting revision")
    for name in ("action", "eventType"):
        text(value[name], name)
    for name in ("nextStateRef", "eventBundleRef", "semanticResultRef", "authorityContextRef"):
        artifact(value[name], name)
    if value["preparedProofInputRef"] is not None:
        artifact(value["preparedProofInputRef"], "preparedProofInputRef")
    effect = value["activationEffect"]
    if effect is not None:
        if type(effect) is not dict or set(effect) != _ACTIVATION_EFFECT_FIELDS:
            invalid("Invalid activationEffect")
        for name in ("closingWindowId", "authorityDomain", "issuerId", "issuerGeneration", "nonce"):
            text(effect[name], name)
        for name in ("commitBoundAuthorityRef", "qualifiedPolicyEffectRef", "windowRequestRef"):
            artifact(effect[name], name)
    return value


def _transition_artifact(value: Any, label: str) -> None:
    try:
        _validate_adoption_ref(value, label)
    except LifecycleError:
        raise LifecycleError("workflow-transition-invalid", f"Invalid {label}") from None


def _transition_digest(value: Any, label: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise LifecycleError("workflow-transition-invalid", f"Invalid {label}")


def _transition_revision(value: Any, label: str) -> None:
    if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
        raise LifecycleError("workflow-transition-invalid", f"Invalid {label}")


def validate_committed_result(value: Any) -> dict[str, Any]:
    """Check immutable result data; publication and current permission stay separate."""
    if (
        type(value) is not dict
        or set(value) != _COMMITTED_RESULT_FIELDS
        or value["schemaVersion"] != COMMITTED_RESULT_V1
    ):
        raise LifecycleError("workflow-transition-invalid", "Invalid CommittedResult")
    for name in ("runId", "operationId"):
        if type(value[name]) is not str or not 1 <= len(value[name]) <= 256:
            raise LifecycleError("workflow-transition-invalid", f"Invalid {name}")
    for name in ("requestDigest", "stateDigest", "eventBundleDigest", "resultDigest"):
        _transition_digest(value[name], name)
    for name in ("beforeRevision", "afterRevision", "projectionGeneration"):
        _transition_revision(value[name], name)
    if value["afterRevision"] != value["beforeRevision"] + 1:
        raise LifecycleError("workflow-transition-invalid", "Committed result revision is not consecutive")
    _transition_artifact(value["semanticResultRef"], "semanticResultRef")
    for name in ("closingWindowId", "policyEventId"):
        item = value[name]
        if item is not None and (type(item) is not str or not 1 <= len(item) <= 256):
            raise LifecycleError("workflow-transition-invalid", f"Invalid {name}")
    for name in (
        "authorityDecisionRef",
        "resourcePolicyEffectRef",
        "deadlineDecisionRef",
        "clockObservationRef",
        "committedProofEnvelopeRef",
    ):
        if value[name] is not None:
            _transition_artifact(value[name], name)
    if canonical_digest({k: v for k, v in value.items() if k != "resultDigest"}) != value["resultDigest"]:
        raise LifecycleError("workflow-transition-invalid", "Committed result digest differs")
    return value


def validate_projection_status(value: Any) -> dict[str, Any]:
    """Validate publication metadata without asserting that files are actually ACKed."""
    if (
        type(value) is not dict
        or set(value) != _PROJECTION_STATUS_FIELDS
        or value["schemaVersion"] != PROJECTION_STATUS_V1
    ):
        raise LifecycleError("workflow-transition-invalid", "Invalid ProjectionStatus")
    if type(value["runId"]) is not str or not 1 <= len(value["runId"]) <= 256:
        raise LifecycleError("workflow-transition-invalid", "Invalid projection runId")
    for name in ("workflowRevision", "generation"):
        _transition_revision(value[name], name)
    for name in ("stateDigest", "eventBundleDigest"):
        _transition_digest(value[name], name)
    if type(value["status"]) is not str or value["status"] not in {"PENDING", "ACK", "UNAVAILABLE"}:
        raise LifecycleError("workflow-transition-invalid", "Invalid projection status")
    if (value["status"] == "ACK") != (value["ackRef"] is not None):
        raise LifecycleError("workflow-transition-invalid", "Projection ACK reference differs")
    for name in ("ackRef", "committedProofEnvelopeRef"):
        if value[name] is not None:
            _transition_artifact(value[name], name)
    return value


_RUNTIME_BINDING_FIELDS = frozenset(
    {
        "schemaVersion",
        "bindingId",
        "runId",
        "packageId",
        "budgetScopeId",
        "canonicalStatePath",
        "journalPath",
        "journalIdentity",
        "storageProtocolVersion",
        "workflowProtocolVersion",
        "planDigest",
        "sourceRevision",
        "adoptionEpoch",
        "authorityMode",
        "workflowAuthorityPinRef",
        "resourceInventoryRef",
        "deadlineInventoryRef",
    }
)


def validate_runtime_binding(value: Any) -> dict[str, Any]:
    """Check the closed wire shape only; the expected digest must be pinned elsewhere."""
    if type(value) is not dict or set(value) != _RUNTIME_BINDING_FIELDS:
        raise LifecycleError("invalid-runtime-binding", "Runtime binding has missing or unknown fields")
    if value["schemaVersion"] != RUNTIME_BINDING_V1 or value["authorityMode"] != "JOURNAL_REQUIRED":
        raise LifecycleError("invalid-runtime-binding", "Unsupported runtime binding mode")
    for name in _RUNTIME_BINDING_FIELDS - {
        "schemaVersion",
        "authorityMode",
        "planDigest",
        "workflowAuthorityPinRef",
        "resourceInventoryRef",
        "deadlineInventoryRef",
    }:
        item = value[name]
        limit = 4096 if name in {"canonicalStatePath", "journalPath"} else 256
        if type(item) is not str or not 1 <= len(item) <= limit:
            raise LifecycleError("invalid-runtime-binding", f"Invalid {name}")
    if type(value["planDigest"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["planDigest"]) is None:
        raise LifecycleError("invalid-runtime-binding", "Invalid planDigest")
    for name in ("workflowAuthorityPinRef", "resourceInventoryRef", "deadlineInventoryRef"):
        ref = value[name]
        if type(ref) is not dict or set(ref) != {"path", "sha256", "bytes"}:
            raise LifecycleError("invalid-runtime-binding", f"Invalid {name}")
        if type(ref["path"]) is not str or not 1 <= len(ref["path"]) <= 4096:
            raise LifecycleError("invalid-runtime-binding", f"Invalid {name}.path")
        if type(ref["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) is None:
            raise LifecycleError("invalid-runtime-binding", f"Invalid {name}.sha256")
        if type(ref["bytes"]) is not int or not 0 <= ref["bytes"] <= 8388608:
            raise LifecycleError("invalid-runtime-binding", f"Invalid {name}.bytes")
    return value


RUN_PHASES = {
    "AWAITING_AUTHORIZATION",
    "PLAN_ONLY",
    "READY",
    "RUNNING",
    "BLOCKED",
    "WAITING_FOR_BUDGET_DECISION",
    "WAITING_FOR_EXTERNAL_ACTION",
    "FINAL_AUDIT",
    "COMPLETE",
    "FAILED",
    "CANCELLED",
}
TASK_STATUSES = {
    "PENDING",
    "READY",
    "RUNNING",
    "VERIFYING",
    "REWORK",
    "ACCEPTED",
    "CONTRACT_CHANGE",
    "BLOCKED",
}

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_TASK_ID = {"type": "string", "minLength": 1, "maxLength": 256}
_CLOSING_ACTIONS = frozenset(
    {
        "read-evidence",
        "assess-evidence",
        "report",
        "final-audit",
        "final-check",
        "apply-final-outcome",
        "finalize",
        "accounting-closeout",
    }
)
_CLOSING_FIELDS = frozenset(
    {
        "schemaVersion",
        "mode",
        "runId",
        "packageId",
        "planDigest",
        "sourceRevision",
        "bindingId",
        "journalIdentity",
        "closingWindowId",
        "activationRevision",
        "windowGrantDigest",
        "authorityDecisionDigest",
        "resourcePolicyEffectDigest",
        "deadlineDecisionDigest",
        "originalDeadlineDigest",
        "originalOutcomeDigest",
        "originalFinancialDigest",
        "validFrom",
        "expiresAt",
        "allowedActions",
        "contextDigest",
    }
)

_TRANSITION_ARTIFACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path", "sha256", "bytes"],
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 4096},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "bytes": {"type": "integer", "minimum": 0, "maximum": 8_388_608},
    },
}
_TRANSITION_TEXT_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 256}
_TRANSITION_DIGEST_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_TRANSITION_REVISION_SCHEMA = {"type": "integer", "minimum": 0, "maximum": 9_007_199_254_740_991}
_TRANSITION_NULLABLE_REF_SCHEMA = {"anyOf": [{"$ref": "#/$defs/ArtifactRef"}, {"type": "null"}]}

WORKFLOW_STATE_SCHEMAS: dict[str, dict[str, Any]] = {
    COMMITTED_RESULT_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": COMMITTED_RESULT_V1,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "runId",
            "operationId",
            "requestDigest",
            "beforeRevision",
            "afterRevision",
            "stateDigest",
            "eventBundleDigest",
            "semanticResultRef",
            "closingWindowId",
            "policyEventId",
            "projectionGeneration",
            "resultDigest",
            "authorityDecisionRef",
            "resourcePolicyEffectRef",
            "deadlineDecisionRef",
            "clockObservationRef",
            "committedProofEnvelopeRef",
        ],
        "$defs": {"ArtifactRef": _TRANSITION_ARTIFACT_SCHEMA},
        "properties": {
            "schemaVersion": {"const": COMMITTED_RESULT_V1},
            **{name: _TRANSITION_TEXT_SCHEMA for name in ("runId", "operationId")},
            **{
                name: _TRANSITION_DIGEST_SCHEMA
                for name in ("requestDigest", "stateDigest", "eventBundleDigest", "resultDigest")
            },
            **{
                name: _TRANSITION_REVISION_SCHEMA
                for name in ("beforeRevision", "afterRevision", "projectionGeneration")
            },
            "semanticResultRef": {"$ref": "#/$defs/ArtifactRef"},
            **{
                name: {"anyOf": [_TRANSITION_TEXT_SCHEMA, {"type": "null"}]}
                for name in ("closingWindowId", "policyEventId")
            },
            **{
                name: _TRANSITION_NULLABLE_REF_SCHEMA
                for name in (
                    "authorityDecisionRef",
                    "resourcePolicyEffectRef",
                    "deadlineDecisionRef",
                    "clockObservationRef",
                    "committedProofEnvelopeRef",
                )
            },
        },
    },
    PROJECTION_STATUS_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROJECTION_STATUS_V1,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "runId",
            "workflowRevision",
            "generation",
            "stateDigest",
            "eventBundleDigest",
            "status",
            "ackRef",
            "committedProofEnvelopeRef",
        ],
        "$defs": {"ArtifactRef": _TRANSITION_ARTIFACT_SCHEMA},
        "properties": {
            "schemaVersion": {"const": PROJECTION_STATUS_V1},
            "runId": _TRANSITION_TEXT_SCHEMA,
            **{name: _TRANSITION_REVISION_SCHEMA for name in ("workflowRevision", "generation")},
            **{name: _TRANSITION_DIGEST_SCHEMA for name in ("stateDigest", "eventBundleDigest")},
            "status": {"enum": ["PENDING", "ACK", "UNAVAILABLE"]},
            "ackRef": _TRANSITION_NULLABLE_REF_SCHEMA,
            "committedProofEnvelopeRef": _TRANSITION_NULLABLE_REF_SCHEMA,
        },
    },
    TRANSITION_REQUEST_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": TRANSITION_REQUEST_V1,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_TRANSITION_FIELDS),
        "$defs": {
            "ArtifactRef": _TRANSITION_ARTIFACT_SCHEMA,
            "BindingRef": {
                "type": "object",
                "additionalProperties": False,
                "required": ["bindingId", "expectedBindingDigest"],
                "properties": {
                    "bindingId": {"type": "string", "minLength": 1, "maxLength": 256},
                    "expectedBindingDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
            },
            "AccountingRevision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["budgetScopeId", "revision"],
                "properties": {
                    "budgetScopeId": {"type": "string", "minLength": 1, "maxLength": 256},
                    "revision": {"type": "integer", "minimum": 0, "maximum": 9_007_199_254_740_991},
                },
            },
            "ActivationEffect": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "closingWindowId",
                    "authorityDomain",
                    "issuerId",
                    "issuerGeneration",
                    "nonce",
                    "commitBoundAuthorityRef",
                    "qualifiedPolicyEffectRef",
                    "windowRequestRef",
                ],
                "properties": {
                    **{
                        name: {"type": "string", "minLength": 1, "maxLength": 256}
                        for name in ("closingWindowId", "authorityDomain", "issuerId", "issuerGeneration", "nonce")
                    },
                    **{
                        name: {"$ref": "#/$defs/ArtifactRef"}
                        for name in ("commitBoundAuthorityRef", "qualifiedPolicyEffectRef", "windowRequestRef")
                    },
                },
            },
        },
        "properties": {
            "schemaVersion": {"const": TRANSITION_REQUEST_V1},
            "binding": {"$ref": "#/$defs/BindingRef"},
            "operationId": {"type": "string", "minLength": 1, "maxLength": 256},
            "requestDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "expectedWorkflowRevision": {"type": "integer", "minimum": 0, "maximum": 9_007_199_254_740_991},
            "expectedAccountingRevisions": {
                "type": "array",
                "items": {"$ref": "#/$defs/AccountingRevision"},
                "maxItems": 64,
                "uniqueItems": True,
            },
            "action": {"type": "string", "minLength": 1, "maxLength": 256},
            "eventType": {"type": "string", "minLength": 1, "maxLength": 256},
            **{
                name: {"$ref": "#/$defs/ArtifactRef"}
                for name in ("nextStateRef", "eventBundleRef", "semanticResultRef", "authorityContextRef")
            },
            "activationEffect": {"anyOf": [{"$ref": "#/$defs/ActivationEffect"}, {"type": "null"}]},
            "preparedProofInputRef": {"anyOf": [{"$ref": "#/$defs/ArtifactRef"}, {"type": "null"}]},
        },
    },
    ADOPTION_INPUT_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ADOPTION_INPUT_V1,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_ADOPTION_INPUT_FIELDS),
        "$defs": {
            "ArtifactRef": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_ADOPTION_REF_FIELDS),
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "bytes": {"type": "integer", "minimum": 0, "maximum": 8_388_608},
                },
            }
        },
        "properties": {
            "schemaVersion": {"const": ADOPTION_INPUT_V1},
            "operationId": {"type": "string", "minLength": 1, "maxLength": 256},
            **{
                name: {"$ref": "#/$defs/ArtifactRef"} for name in ("bindingRef", "legacyStateRef", "initialSnapshotRef")
            },
            "legacyEventLogRef": {"anyOf": [{"$ref": "#/$defs/ArtifactRef"}, {"type": "null"}]},
            "accountingMode": {"const": "EXISTING_QUALIFIED_SCOPE"},
        },
    },
    ADOPTION_SELECTION_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ADOPTION_SELECTION_V1,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_ADOPTION_SELECTION_FIELDS),
        "$defs": {
            "ArtifactRef": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_ADOPTION_REF_FIELDS),
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "bytes": {"type": "integer", "minimum": 0, "maximum": 8_388_608},
                },
            }
        },
        "properties": {
            "schemaVersion": {"const": ADOPTION_SELECTION_V1},
            **{
                name: {"type": "string", "pattern": "^[0-9a-f]{64}$"}
                for name in (
                    "expectedBindingDigest",
                    "expectedPinDigest",
                    "expectedInitialSnapshotDigest",
                    "expectedAccountingStateDigest",
                )
            },
            "expectedAccountingRevision": {"type": "integer", "minimum": 0, "maximum": 9_007_199_254_740_991},
            **{
                name: {"type": "string", "minLength": 1, "maxLength": 256}
                for name in ("expectedJournalIdentity", "expectedBudgetScopeId")
            },
            "expectedStorageProtocolVersion": {"const": "5"},
            "expectedWorkflowProtocolVersion": {"const": "1"},
            **{
                name: {"$ref": "#/$defs/ArtifactRef"}
                for name in ("operatorQualificationRef", "quiescenceEvidenceRef", "writerInventoryRef")
            },
        },
    },
    RUNTIME_BINDING_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": RUNTIME_BINDING_V1,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_RUNTIME_BINDING_FIELDS),
        "properties": {
            "schemaVersion": {"const": RUNTIME_BINDING_V1},
            "authorityMode": {"const": "JOURNAL_REQUIRED"},
            "planDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            **{
                name: {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096 if name in {"canonicalStatePath", "journalPath"} else 256,
                }
                for name in _RUNTIME_BINDING_FIELDS
                - {
                    "schemaVersion",
                    "authorityMode",
                    "planDigest",
                    "workflowAuthorityPinRef",
                    "resourceInventoryRef",
                    "deadlineInventoryRef",
                }
            },
            **{
                name: {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "sha256", "bytes"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "bytes": {"type": "integer", "minimum": 0, "maximum": 8388608},
                    },
                }
                for name in ("workflowAuthorityPinRef", "resourceInventoryRef", "deadlineInventoryRef")
            },
        },
    },
    CLOSING_CONTEXT_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CLOSING_CONTEXT_V1,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_CLOSING_FIELDS),
        "properties": {
            **{
                name: {"type": "string", "minLength": 1, "maxLength": 256}
                for name in ("runId", "packageId", "sourceRevision", "bindingId", "journalIdentity", "closingWindowId")
            },
            **{
                name: _DIGEST
                for name in (
                    "planDigest",
                    "windowGrantDigest",
                    "authorityDecisionDigest",
                    "resourcePolicyEffectDigest",
                    "deadlineDecisionDigest",
                    "originalDeadlineDigest",
                    "originalOutcomeDigest",
                    "originalFinancialDigest",
                    "contextDigest",
                )
            },
            "schemaVersion": {"const": CLOSING_CONTEXT_V1},
            "mode": {"const": "CLOSING_ONLY"},
            "activationRevision": {"type": "integer", "minimum": 1},
            "validFrom": {"type": "string", "minLength": 1},
            "expiresAt": {"type": "string", "minLength": 1},
            "allowedActions": {
                "type": "array",
                "items": {"enum": sorted(_CLOSING_ACTIONS)},
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
            },
        },
    },
    WORKFLOW_STATE_V4: open_object_schema(
        WORKFLOW_STATE_V4,
        required=[
            "schemaVersion",
            "runId",
            "packageId",
            "stateRevision",
            "phase",
            "tasks",
            "operationLedger",
            "eventLog",
        ],
        properties={
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": "string", "minLength": 1},
            "planRevision": {"type": "integer", "minimum": 0},
            "planDigest": {"type": "string", "minLength": 0, "maxLength": 64},
            "sourceRevision": {"type": "string", "minLength": 0},
            "stateRevision": {"type": "integer", "minimum": 1},
            "phase": {"enum": sorted(RUN_PHASES)},
            "tasks": {"type": "array"},
            "operationLedger": {"type": "object"},
            "eventLog": {"type": "string", "minLength": 1},
            "authorization": {"type": "object"},
            "budgets": {"type": "object"},
            "attemptHistory": {"type": "array"},
            "immutableInput": {"type": "object"},
            "closingWindow": {"type": "object"},
        },
    ),
    WORKFLOW_STATE_MIGRATION_RECEIPT: open_object_schema(
        WORKFLOW_STATE_MIGRATION_RECEIPT,
        required=[
            "schemaVersion",
            "status",
            "runId",
            "packageId",
            "fromSchemaVersion",
            "toSchemaVersion",
            "sourceStateRevision",
            "targetStateRevision",
            "operationId",
            "receiptDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": "string", "minLength": 1},
            "fromSchemaVersion": {"const": WORKFLOW_STATE_V3},
            "toSchemaVersion": {"const": WORKFLOW_STATE_V4},
            "sourceStateRevision": {"type": "integer", "minimum": 1},
            "targetStateRevision": {"type": "integer", "minimum": 2},
            "operationId": {"type": "string", "minLength": 1},
            "receiptDigest": _DIGEST,
        },
    ),
}


def has_current_workflow_semantics(state: dict[str, Any]) -> bool:
    """v5 changes storage representation and retains all v4 authority rules."""
    return state.get("schemaVersion") in {WORKFLOW_STATE_V4, WORKFLOW_STATE_V5}


WORKFLOW_STATE_SCHEMAS[WORKFLOW_STATE_V5] = deepcopy(WORKFLOW_STATE_SCHEMAS[WORKFLOW_STATE_V4])
WORKFLOW_STATE_SCHEMAS[WORKFLOW_STATE_V5].update({"$id": WORKFLOW_STATE_V5})
WORKFLOW_STATE_SCHEMAS[WORKFLOW_STATE_V5]["properties"]["schemaVersion"] = {
    "const": WORKFLOW_STATE_V5,
}
WORKFLOW_STATE_SCHEMAS[WORKFLOW_STATE_V5]["required"].append("storage")
WORKFLOW_STATE_SCHEMAS[WORKFLOW_STATE_V5]["properties"]["storage"] = {
    "type": "object",
    "required": ["schemaVersion", "root"],
    "additionalProperties": False,
    "properties": {
        "schemaVersion": {"const": "agent-workflow-storage.v1"},
        "root": {"type": "string", "minLength": 1},
    },
}


def validate_workflow_state(state: dict[str, Any], *, allow_legacy: bool = True) -> dict[str, Any]:
    """Validate state shape and cross-field invariants before it is trusted."""

    if not isinstance(state, dict):
        raise LifecycleError("invalid-workflow-state", "workflow state must be an object")
    schema_version = state.get("schemaVersion")
    if schema_version == WORKFLOW_STATE_V3 and allow_legacy:
        _validate_legacy_state(state)
        _validate_a5_state(state)
        if "closingWindow" in state:
            raise LifecycleError("closing-context-invalid", "Legacy state cannot carry an active closing context")
        return state
    if not has_current_workflow_semantics(state):
        raise LifecycleError("unsupported-workflow-state", "workflow state schemaVersion is unsupported")
    if schema_version == WORKFLOW_STATE_V5:
        validate_storage_metadata(state.get("storage"))
        validate_storage_counts(state)
    _require_string(state, "runId")
    _require_string(state, "packageId")
    _require_positive_int(state, "stateRevision")
    phase = state.get("phase")
    if phase not in RUN_PHASES:
        raise LifecycleError("invalid-workflow-state", "workflow state phase is unsupported")
    if not isinstance(state.get("tasks"), list):
        raise LifecycleError("invalid-workflow-state", "tasks must be an array")
    if not isinstance(state.get("operationLedger"), dict):
        raise LifecycleError("invalid-workflow-state", "operationLedger must be an object")
    _validate_storage_paths(state)
    _validate_tasks(state)
    _validate_phase_invariants(state)
    _validate_a5_state(state)
    if "closingWindow" in state:
        validate_closing_context(state["closingWindow"], state=state)
    return state


def validate_closing_context(value: Any, *, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate closed structural data; this never authenticates the window."""
    if type(value) is not dict or set(value) != _CLOSING_FIELDS:
        raise LifecycleError("closing-context-invalid", "Closing context has missing or unknown fields")
    if value["schemaVersion"] != "agent-closing-context.v1" or value["mode"] != "CLOSING_ONLY":
        raise LifecycleError("closing-context-invalid", "Unsupported active closing context")
    for name in ("runId", "packageId", "sourceRevision", "bindingId", "journalIdentity", "closingWindowId"):
        field = value[name]
        if type(field) is not str or not 1 <= len(field) <= 256:
            raise LifecycleError("closing-context-invalid", f"Invalid {name}")
    for name in (
        "planDigest",
        "windowGrantDigest",
        "authorityDecisionDigest",
        "resourcePolicyEffectDigest",
        "deadlineDecisionDigest",
        "originalDeadlineDigest",
        "originalOutcomeDigest",
        "originalFinancialDigest",
        "contextDigest",
    ):
        if type(value[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[name]) is None:
            raise LifecycleError("closing-context-invalid", f"Invalid {name}")
    revision = value["activationRevision"]
    if type(revision) is not int or revision < 1:
        raise LifecycleError("closing-context-invalid", "Invalid activation revision")
    actions = value["allowedActions"]
    if (
        type(actions) is not list
        or not actions
        or len(actions) > 8
        or any(type(action) is not str for action in actions)
        or set(actions) - _CLOSING_ACTIONS
        or len(actions) != len(set(actions))
    ):
        raise LifecycleError("closing-context-invalid", "Invalid closing action set")
    if _closing_instant(value["validFrom"], "validFrom") >= _closing_instant(value["expiresAt"], "expiresAt"):
        raise LifecycleError("closing-context-invalid", "Closing interval must be finite and ordered")
    body = {key: item for key, item in value.items() if key != "contextDigest"}
    if canonical_digest(body) != value["contextDigest"]:
        raise LifecycleError("closing-context-invalid", "Closing context digest mismatch")
    if state is not None and (
        any(value[key] != state.get(key) for key in ("runId", "packageId", "planDigest", "sourceRevision"))
        or revision > state.get("stateRevision", 0)
    ):
        raise LifecycleError("closing-context-invalid", "Closing context does not match workflow state")
    return value


def _validate_storage_paths(state: dict[str, Any]) -> None:
    event_log = state.get("eventLog")
    if not isinstance(event_log, str):
        raise LifecycleError("invalid-workflow-state", "eventLog must be a portable relative path")
    try:
        normalize_repo_path(event_log, label="eventLog")
    except LifecycleError:
        raise LifecycleError("invalid-workflow-state", "eventLog must be a portable relative path") from None
    root = state.get("packageRoot", ".")
    if not isinstance(root, str) or not root:
        raise LifecycleError("invalid-workflow-state", "packageRoot must be a relative path")
    try:
        if len(root.encode("utf-8")) > MAX_REPO_PATH_BYTES:
            raise ValueError
        if root != ".":
            # Parent anchors are lexical input, never a grant to escape the runtime root.
            parts = root.split("/")
            first = 0
            while first < len(parts) and parts[first] == "..":
                first += 1
            if first < len(parts):
                normalize_repo_path("/".join(parts[first:]), label="packageRoot")
    except (UnicodeError, ValueError, LifecycleError):
        raise LifecycleError("invalid-workflow-state", "packageRoot must be a portable relative path") from None


def _validate_legacy_state(state: dict[str, Any]) -> None:
    _require_positive_int(state, "stateRevision")
    if not isinstance(state.get("phase"), str) or not state["phase"]:
        raise LifecycleError("invalid-workflow-state", "phase is required")
    if not isinstance(state.get("tasks"), list):
        raise LifecycleError("invalid-workflow-state", "tasks must be an array")


def _validate_tasks(state: dict[str, Any]) -> None:
    seen: set[str] = set()
    task_ids = {task.get("id") for task in state["tasks"] if isinstance(task, dict) and isinstance(task.get("id"), str)}
    for task in state["tasks"]:
        if not isinstance(task, dict):
            raise LifecycleError("invalid-workflow-state", "task entries must be objects")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id or task_id in seen:
            raise LifecycleError("invalid-workflow-state", "task IDs must be unique non-empty strings")
        seen.add(task_id)
        if task.get("status") not in TASK_STATUSES:
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has an unsupported status")
        attempt = task.get("attempt", 0)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has an invalid attempt")
        dependencies = task.get("dependsOn", [])
        if not isinstance(dependencies, list) or any(item not in task_ids for item in dependencies):
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has invalid dependencies")
        history = task.get("attemptHistory", [])
        if not isinstance(history, list) or len(history) > attempt:
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has incoherent attempt history")
        if task.get("status") == "ACCEPTED" and any(
            key in task for key in ("attemptStartedAt", "attemptDeadlineAt", "attemptModelRoute")
        ):
            raise LifecycleError("invalid-workflow-state", f"accepted task {task_id} has active attempt state")
        if task.get("status") == "BLOCKED" and not isinstance(task.get("blocker"), dict):
            raise LifecycleError("invalid-workflow-state", f"blocked task {task_id} requires a typed blocker")
        if task.get("status") == "CONTRACT_CHANGE" and not isinstance(task.get("contractChangeRequest"), dict):
            raise LifecycleError(
                "invalid-workflow-state",
                f"contract-change task {task_id} requires a typed request",
            )


def _validate_phase_invariants(state: dict[str, Any]) -> None:
    required = [task for task in state["tasks"] if task.get("required", True)]
    if state["phase"] == "FINAL_AUDIT" and any(task.get("status") != "ACCEPTED" for task in required):
        raise LifecycleError("invalid-workflow-state", "FINAL_AUDIT requires every required task to be ACCEPTED")
    if state["phase"] == "BLOCKED" and not isinstance(state.get("blocker"), dict):
        raise LifecycleError("invalid-workflow-state", "BLOCKED state requires a typed blocker")


def _require_string(state: dict[str, Any], key: str) -> None:
    if not isinstance(state.get(key), str) or not state[key]:
        raise LifecycleError("invalid-workflow-state", f"{key} must be a non-empty string")


def _require_positive_int(state: dict[str, Any], key: str) -> None:
    value = state.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError("invalid-workflow-state", f"{key} must be a positive integer")


__all__ = [
    "CLOSING_CONTEXT_V1",
    "RUNTIME_BINDING_V1",
    "RUN_PHASES",
    "TASK_STATUSES",
    "WORKFLOW_STATE_MIGRATION_RECEIPT",
    "WORKFLOW_STATE_SCHEMAS",
    "WORKFLOW_STATE_V3",
    "WORKFLOW_STATE_V4",
    "validate_closing_context",
    "validate_runtime_binding",
    "validate_workflow_state",
]
