"""Portable contracts for the optional security-analysis profile."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

SECURITY_ANALYSIS_PROFILE_SCHEMA = "agent-security-analysis-profile.v1"
SECURITY_ANALYSIS_PROFILE_VALIDATION_SCHEMA = "agent-security-analysis-profile-validation.v1"
SECURITY_FINDING_SCHEMA = "agent-security-finding.v1"
SECURITY_FINDING_VALIDATION_SCHEMA = "agent-security-finding-validation.v1"
SECURITY_FINDING_IMPORT_SCHEMA = "agent-security-finding-import.v1"
SECURITY_FINDING_IMPORT_VALIDATION_SCHEMA = "agent-security-finding-import-validation.v1"
SECURITY_EXECUTION_GATE_SCHEMA = "agent-security-execution-gate.v1"
SECURITY_EXECUTION_GATE_VALIDATION_SCHEMA = "agent-security-execution-gate-validation.v1"
SECURITY_VERIFICATION_ASSIGNMENT_SCHEMA = "agent-security-verification-assignment.v1"
SECURITY_VERIFICATION_ASSIGNMENT_VALIDATION_SCHEMA = "agent-security-verification-assignment-validation.v1"
SECURITY_ANALYSIS_AUDIT_SCHEMA = "agent-security-analysis-audit.v1"
SECURITY_ANALYSIS_AUDIT_VALIDATION_SCHEMA = "agent-security-analysis-audit-validation.v1"

SECURITY_SEVERITIES = ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
SECURITY_CONFIDENCES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH")
SECURITY_FINDING_STATUSES = ("UNTRUSTED", "VALIDATED", "REJECTED", "DISPUTED")

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}

SECURITY_ANALYSIS_SCHEMAS: dict[str, dict[str, Any]] = {
    SECURITY_ANALYSIS_PROFILE_SCHEMA: open_object_schema(
        SECURITY_ANALYSIS_PROFILE_SCHEMA,
        required=[
            "schemaVersion",
            "profileId",
            "status",
            "enabledByDefault",
            "activationMode",
            "stages",
            "findingsPolicy",
            "executionPolicy",
            "implementationAudit",
            "productionPromotionClaimed",
            "profileDigest",
        ],
        properties={
            "profileId": {"const": "security-analysis"},
            "status": {"const": "OPTIONAL"},
            "enabledByDefault": {"const": False},
            "activationMode": {"const": "explicit-task-trigger"},
            "stages": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "findingsPolicy": {"type": "object"},
            "executionPolicy": {"type": "object"},
            "implementationAudit": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
            "profileDigest": _DIGEST,
        },
    ),
    SECURITY_ANALYSIS_PROFILE_VALIDATION_SCHEMA: open_object_schema(
        SECURITY_ANALYSIS_PROFILE_VALIDATION_SCHEMA,
        required=["schemaVersion", "status", "profileId", "blockers", "profileDigest", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "profileId": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "profileDigest": {"type": ["string", "null"]},
            "validationDigest": _DIGEST,
        },
    ),
    SECURITY_FINDING_SCHEMA: open_object_schema(
        SECURITY_FINDING_SCHEMA,
        required=[
            "schemaVersion",
            "findingId",
            "title",
            "severity",
            "confidence",
            "status",
            "sourceRevision",
            "sourceLineageDigest",
            "locations",
            "trusted",
            "authorityClaimed",
            "productionPromotionClaimed",
            "findingDigest",
        ],
        properties={
            "findingId": {"type": "string", "minLength": 1, "maxLength": 256},
            "title": {"type": "string", "minLength": 1, "maxLength": 4096},
            "description": {"type": "string", "maxLength": 16384},
            "severity": {"enum": list(SECURITY_SEVERITIES)},
            "confidence": {"enum": list(SECURITY_CONFIDENCES)},
            "status": {"enum": list(SECURITY_FINDING_STATUSES)},
            "source": {"type": "object"},
            "sourceRevision": {"type": "string", "minLength": 1},
            "sourceLineageDigest": _DIGEST,
            "locations": {"type": "array", "items": {"type": "object"}, "maxItems": 64},
            "remediation": {"type": ["object", "null"]},
            "trusted": {"const": False},
            "authorityClaimed": {"const": False},
            "evidenceIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "productionPromotionClaimed": {"const": False},
            "findingDigest": _DIGEST,
        },
    ),
    SECURITY_FINDING_VALIDATION_SCHEMA: open_object_schema(
        SECURITY_FINDING_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "findingId",
            "findingStatus",
            "blockers",
            "findingDigest",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "findingId": {"type": ["string", "null"]},
            "findingStatus": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "findingDigest": {"type": ["string", "null"]},
            "validationDigest": _DIGEST,
        },
    ),
    SECURITY_FINDING_IMPORT_SCHEMA: open_object_schema(
        SECURITY_FINDING_IMPORT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "sourceFormat",
            "sourceRevision",
            "findings",
            "trusted",
            "authorityClaimed",
            "blockers",
            "productionPromotionClaimed",
            "importDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "sourceFormat": {"enum": ["SARIF", "NORMALIZED"]},
            "sourceRevision": {"type": "string", "minLength": 1},
            "sourceLineageDigest": {"type": ["string", "null"]},
            "findings": {"type": "array", "items": {"type": "object"}, "maxItems": 4096},
            "trusted": {"const": False},
            "authorityClaimed": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "importDigest": _DIGEST,
        },
    ),
    SECURITY_FINDING_IMPORT_VALIDATION_SCHEMA: open_object_schema(
        SECURITY_FINDING_IMPORT_VALIDATION_SCHEMA,
        required=["schemaVersion", "status", "findingCount", "blockers", "importDigest", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "findingCount": {"type": "integer", "minimum": 0},
            "blockers": _BLOCKERS,
            "importDigest": {"type": ["string", "null"]},
            "validationDigest": _DIGEST,
        },
    ),
    SECURITY_EXECUTION_GATE_SCHEMA: open_object_schema(
        SECURITY_EXECUTION_GATE_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "taskId",
            "activated",
            "explicitOptIn",
            "sandboxReceiptDigest",
            "authorizationGranted",
            "limits",
            "liveCallsStarted",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL", "SKIPPED"]},
            "taskId": {"type": ["string", "null"]},
            "activated": {"type": "boolean"},
            "explicitOptIn": {"type": "boolean"},
            "sandboxReceiptDigest": {"type": ["string", "null"]},
            "authorizationGranted": {"type": "boolean"},
            "limits": {"type": "object"},
            "liveCallsStarted": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    SECURITY_EXECUTION_GATE_VALIDATION_SCHEMA: open_object_schema(
        SECURITY_EXECUTION_GATE_VALIDATION_SCHEMA,
        required=["schemaVersion", "status", "gateStatus", "blockers", "receiptDigest", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "gateStatus": {"enum": ["PASS", "FAIL", "SKIPPED"]},
            "blockers": _BLOCKERS,
            "receiptDigest": {"type": ["string", "null"]},
            "validationDigest": _DIGEST,
        },
    ),
    SECURITY_VERIFICATION_ASSIGNMENT_SCHEMA: open_object_schema(
        SECURITY_VERIFICATION_ASSIGNMENT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "assignmentId",
            "runId",
            "taskId",
            "attempt",
            "planDigest",
            "sourceRevision",
            "reviewer",
            "independentEvidenceIds",
            "productionPromotionClaimed",
            "assignmentDigest",
        ],
        properties={
            "status": {"enum": ["READY", "PASS", "FAIL", "DISPUTED"]},
            "assignmentId": {"type": "string", "minLength": 1},
            "runId": {"type": "string", "minLength": 1},
            "taskId": {"type": "string", "minLength": 1},
            "attempt": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "sourceRevision": {"type": "string", "minLength": 1},
            "reviewer": {"type": "object"},
            "independentEvidenceIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "productionPromotionClaimed": {"const": False},
            "assignmentDigest": _DIGEST,
        },
    ),
    SECURITY_VERIFICATION_ASSIGNMENT_VALIDATION_SCHEMA: open_object_schema(
        SECURITY_VERIFICATION_ASSIGNMENT_VALIDATION_SCHEMA,
        required=["schemaVersion", "status", "blockers", "assignmentDigest", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "blockers": _BLOCKERS,
            "assignmentDigest": {"type": ["string", "null"]},
            "validationDigest": _DIGEST,
        },
    ),
    SECURITY_ANALYSIS_AUDIT_SCHEMA: open_object_schema(
        SECURITY_ANALYSIS_AUDIT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "verdict",
            "runId",
            "taskId",
            "attempt",
            "planDigest",
            "sourceRevision",
            "auditor",
            "findings",
            "independentEvidenceIds",
            "productionPromotionClaimed",
            "auditDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL", "DISPUTED"]},
            "verdict": {"enum": ["ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"]},
            "runId": {"type": "string", "minLength": 1},
            "taskId": {"type": "string", "minLength": 1},
            "attempt": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "sourceRevision": {"type": "string", "minLength": 1},
            "auditor": {"type": "object"},
            "findings": {"type": "array", "items": {"type": "object"}},
            "independentEvidenceIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "productionPromotionClaimed": {"const": False},
            "auditDigest": _DIGEST,
        },
    ),
    SECURITY_ANALYSIS_AUDIT_VALIDATION_SCHEMA: open_object_schema(
        SECURITY_ANALYSIS_AUDIT_VALIDATION_SCHEMA,
        required=["schemaVersion", "status", "verdict", "blockers", "auditDigest", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "verdict": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "auditDigest": {"type": ["string", "null"]},
            "validationDigest": _DIGEST,
        },
    ),
}

__all__ = [
    "SECURITY_ANALYSIS_AUDIT_SCHEMA",
    "SECURITY_ANALYSIS_AUDIT_VALIDATION_SCHEMA",
    "SECURITY_ANALYSIS_PROFILE_SCHEMA",
    "SECURITY_ANALYSIS_PROFILE_VALIDATION_SCHEMA",
    "SECURITY_ANALYSIS_SCHEMAS",
    "SECURITY_CONFIDENCES",
    "SECURITY_EXECUTION_GATE_SCHEMA",
    "SECURITY_EXECUTION_GATE_VALIDATION_SCHEMA",
    "SECURITY_FINDING_IMPORT_SCHEMA",
    "SECURITY_FINDING_IMPORT_VALIDATION_SCHEMA",
    "SECURITY_FINDING_SCHEMA",
    "SECURITY_FINDING_STATUSES",
    "SECURITY_FINDING_VALIDATION_SCHEMA",
    "SECURITY_SEVERITIES",
    "SECURITY_VERIFICATION_ASSIGNMENT_SCHEMA",
    "SECURITY_VERIFICATION_ASSIGNMENT_VALIDATION_SCHEMA",
]
