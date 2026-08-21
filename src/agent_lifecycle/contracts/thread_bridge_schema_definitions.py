"""Portable contracts for the optional host-thread bridge."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

THREAD_CAPABILITY_SCHEMA = "agent-thread-capability.v1"
THREAD_OPERATION_REQUEST_SCHEMA = "agent-thread-operation-request.v1"
THREAD_OPERATION_RECEIPT_SCHEMA = "agent-thread-operation-receipt.v1"
THREAD_CONTEXT_IMPORT_SCHEMA = "agent-thread-context-import.v1"
THREAD_OPERATION_VALIDATION_SCHEMA = "agent-thread-operation-validation.v1"
THREAD_BRIDGE_PROFILE_SCHEMA = "agent-thread-bridge-profile.v1"
THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA = "agent-thread-bridge-qualification-receipt.v1"
THREAD_BRIDGE_PROFILE_VALIDATION_SCHEMA = "agent-thread-bridge-profile-validation.v1"

THREAD_OPERATIONS = ("read", "list", "send", "create")
THREAD_READ_OPERATIONS = {"read", "list"}
THREAD_MUTATING_OPERATIONS = {"send", "create"}
THREAD_SUPPORT_VALUES = ("supported", "unsupported", "unknown")
THREAD_ADAPTER_STATUS_VALUES = ("UNSUPPORTED", "WRAPPER_ONLY", "SUPPORTED")
THREAD_EFFECTIVE_STATUS_VALUES = THREAD_ADAPTER_STATUS_VALUES
THREAD_QUALIFICATION_STATUS_VALUES = ("UNQUALIFIED", "QUALIFIED", "STALE", "INVALID")
THREAD_OPERATION_STATUSES = ("PASS", "FAIL", "BLOCKED", "UNAVAILABLE")
THREAD_SCOPES = ("explicit-target", "project", "workflow")
THREAD_APPROVALS = ("none", "operator")
THREAD_BRIDGE_MODES = ("off", "advisory", "read-only", "controlled")
THREAD_BRIDGE_POLICY_VERSION = "agent-thread-bridge-policy.v1"

_AUTHORITY_KEYS = {
    "approveTools",
    "developerInstruction",
    "execute",
    "freezePlan",
    "hostCommand",
    "lifecycleTransition",
    "prompt",
    "promptAuthority",
    "runCommand",
    "systemInstruction",
    "taskAccept",
    "toolApproval",
}
_AUTHORITY_MARKERS = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?previous|execute\s+(?:the\s+)?(?:tool|command)|"
    r"approve\s+(?:all\s+)?tools|system\s+instruction|developer\s+instruction|"
    r"bypass\s+(?:review|freeze)|freeze\s+(?:the\s+)?plan|accept\s+(?:the\s+)?task)\b",
    re.IGNORECASE,
)

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}


THREAD_BRIDGE_SCHEMAS: dict[str, dict[str, Any]] = {
    THREAD_BRIDGE_PROFILE_SCHEMA: open_object_schema(
        THREAD_BRIDGE_PROFILE_SCHEMA,
        required=[
            "schemaVersion",
            "profileId",
            "adapterId",
            "host",
            "policyVersion",
            "operations",
            "transport",
            "evidencePolicy",
            "providerIdentityUsed",
            "hostExecutionOwned",
            "productionPromotionClaimed",
            "profileDigest",
        ],
        properties={
            "profileId": {"const": "thread-bridge"},
            "adapterId": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "descriptorDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "capabilityManifestDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "hostRange": {"type": "object"},
            "policyVersion": {"const": THREAD_BRIDGE_POLICY_VERSION},
            "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 4},
            "transport": {"const": "adapter-owned"},
            "evidencePolicy": {"enum": ["qualification-required", "not-claimed"]},
            "providerIdentityUsed": {"const": False},
            "hostExecutionOwned": {"const": True},
            "qualificationRequired": {"const": True},
            "productionPromotionClaimed": {"const": False},
            "profileDigest": _DIGEST,
        },
    ),
    THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA: open_object_schema(
        THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA,
        required=[
            "schemaVersion",
            "receiptId",
            "adapterId",
            "host",
            "descriptorDigest",
            "capabilityManifestDigest",
            "hostRange",
            "policyVersion",
            "operationSet",
            "route",
            "qualificationStatus",
            "evidenceRefs",
            "hostExecutionStarted",
            "modelCallsStarted",
            "networkCallsStarted",
            "rawContentStored",
            "sourceOfTruth",
            "proof",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "receiptId": {"type": "string", "minLength": 1, "maxLength": 160},
            "adapterId": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "descriptorDigest": _DIGEST,
            "capabilityManifestDigest": _DIGEST,
            "hostRange": {"type": "object"},
            "policyVersion": {"const": THREAD_BRIDGE_POLICY_VERSION},
            "operationSet": {"type": "array", "items": {"enum": list(THREAD_OPERATIONS)}, "minItems": 1, "maxItems": 4},
            "route": {"enum": ["native", "wrapper"]},
            "qualificationStatus": {"const": "QUALIFIED"},
            "evidenceRefs": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
            "expiresAt": {"type": ["string", "null"]},
            "hostExecutionStarted": {"const": True},
            "modelCallsStarted": {"const": False},
            "networkCallsStarted": {"const": False},
            "rawContentStored": {"const": False},
            "sourceOfTruth": {"const": False},
            "proof": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    THREAD_BRIDGE_PROFILE_VALIDATION_SCHEMA: open_object_schema(
        THREAD_BRIDGE_PROFILE_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "checks",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterId": {"type": ["string", "null"]},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    THREAD_CAPABILITY_SCHEMA: open_object_schema(
        THREAD_CAPABILITY_SCHEMA,
        required=[
            "schemaVersion",
            "capabilityId",
            "adapterId",
            "host",
            "support",
            "operations",
            "transport",
            "evidencePolicy",
            "providerIdentityUsed",
            "hostExecutionOwned",
            "productionPromotionClaimed",
            "capabilityDigest",
        ],
        properties={
            "capabilityId": {"const": "thread-bridge"},
            "adapterId": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "support": {"enum": list(THREAD_SUPPORT_VALUES)},
            "operations": {"type": "array", "items": {"type": "object"}, "maxItems": 4},
            "transport": {"const": "adapter-owned"},
            "evidencePolicy": {"enum": ["qualification-required", "not-claimed"]},
            "providerIdentityUsed": {"const": False},
            "hostExecutionOwned": {"const": True},
            "productionPromotionClaimed": {"const": False},
            "capabilityDigest": _DIGEST,
        },
    ),
    THREAD_OPERATION_REQUEST_SCHEMA: open_object_schema(
        THREAD_OPERATION_REQUEST_SCHEMA,
        required=[
            "schemaVersion",
            "operationId",
            "operation",
            "target",
            "payload",
            "authorization",
            "limits",
            "planBinding",
            "hostExecutionAllowed",
            "modelCallsStarted",
            "networkCallsStarted",
            "productionPromotionClaimed",
            "requestDigest",
        ],
        properties={
            "operationId": {"type": "string", "minLength": 1, "maxLength": 160},
            "operation": {"enum": list(THREAD_OPERATIONS)},
            "target": {"type": "object"},
            "payload": {"type": "object"},
            "authorization": {"type": "object"},
            "limits": {"type": "object"},
            "phase": {"type": ["string", "null"]},
            "planBinding": {"type": ["object", "null"]},
            "hostExecutionAllowed": {"const": False},
            "modelCallsStarted": {"const": False},
            "networkCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "requestDigest": _DIGEST,
        },
    ),
    THREAD_OPERATION_RECEIPT_SCHEMA: open_object_schema(
        THREAD_OPERATION_RECEIPT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "operation",
            "target",
            "requestDigest",
            "capabilityDigest",
            "result",
            "redactionStatus",
            "sourceOfTruth",
            "proof",
            "rawContentStored",
            "nativeTargetIdStored",
            "hostExecutionStarted",
            "modelCallsStarted",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": list(THREAD_OPERATION_STATUSES)},
            "operationId": {"type": "string", "minLength": 1},
            "operation": {"enum": list(THREAD_OPERATIONS)},
            "target": {"type": "object"},
            "requestDigest": _DIGEST,
            "capabilityDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "result": {"type": "object"},
            "redactionStatus": {"type": "object"},
            "sourceOfTruth": {"const": False},
            "proof": {"const": False},
            "rawContentStored": {"const": False},
            "nativeTargetIdStored": {"const": False},
            "hostExecutionStarted": {"type": "boolean"},
            "modelCallsStarted": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    THREAD_CONTEXT_IMPORT_SCHEMA: open_object_schema(
        THREAD_CONTEXT_IMPORT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "sourceReceiptDigest",
            "source",
            "content",
            "resourceCaps",
            "redactionStatus",
            "sourceOfTruth",
            "proof",
            "rawContentStored",
            "authority",
            "productionPromotionClaimed",
            "importDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "operationId": {"type": "string", "minLength": 1},
            "sourceReceiptDigest": _DIGEST,
            "source": {"type": "object"},
            "content": {"type": "object"},
            "resourceCaps": {"type": "object"},
            "redactionStatus": {"type": "object"},
            "sourceOfTruth": {"const": False},
            "proof": {"const": False},
            "rawContentStored": {"const": False},
            "authority": {"type": "object"},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "importDigest": _DIGEST,
        },
    ),
    THREAD_OPERATION_VALIDATION_SCHEMA: open_object_schema(
        THREAD_OPERATION_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "checks",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "operationId": {"type": ["string", "null"]},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}
