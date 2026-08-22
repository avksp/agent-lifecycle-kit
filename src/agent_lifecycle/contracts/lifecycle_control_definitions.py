"""Shared constants and field sets for adapter lifecycle control contracts."""

from __future__ import annotations

LIFECYCLE_CONTROL_POLICY_SCHEMA = "agent-lifecycle-control-policy.v1"
LIFECYCLE_CONTROL_POLICY_VALIDATION_SCHEMA = "agent-lifecycle-control-policy-validation.v1"
LIFECYCLE_CONTROL_REQUEST_SCHEMA = "agent-lifecycle-control-request.v1"
LIFECYCLE_CONTROL_DECISION_SCHEMA = "agent-lifecycle-control-decision.v1"
LIFECYCLE_CONTROL_EVENT_SCHEMA = "agent-lifecycle-control-event.v1"
LIFECYCLE_CONTROL_ATTESTATION_SCHEMA = "agent-lifecycle-control-attestation.v1"
LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA = "agent-lifecycle-control-qualification-receipt.v1"
LIFECYCLE_CONTROL_QUALIFICATION_VALIDATION_SCHEMA = "agent-lifecycle-control-qualification-validation.v1"

CONTROL_LEVELS = ("OFF", "GUIDANCE_ONLY", "OBSERVED", "ENFORCED")
CONTROL_OPERATIONS = ("file-edit", "shell-command", "task-accept", "run-finalize")
CONTROL_EVENT_TYPES = ("pre-action", "post-action", "stop")
CONTROL_STATUSES = ("PASS", "FAIL", "BLOCKED", "REVIEW_REQUIRED")
QUALIFICATION_STATUSES = ("QUALIFIED", "NO_RECOMMENDATION", "UNAVAILABLE", "BLOCKED")
MAX_CONTROL_PAYLOAD_BYTES = 8192
DEFAULT_MAX_ATTESTATION_AGE_SECONDS = 300
DEFAULT_MAX_REQUEST_AGE_SECONDS = 3600
DEFAULT_MAX_EVENT_AGE_SECONDS = 3600
MAX_CONTROL_STRING_LENGTH = 128
MAX_CONTROL_NESTING = 128
MAX_CONTROL_REDACTION_STRING_LENGTH = 2048
_LEVEL_RANK = {level: index for index, level in enumerate(CONTROL_LEVELS)}
_DIGEST_FIELDS = ("planDigest", "lockDigest", "actionDigest")


def _fields(value: str) -> set[str]:
    return set(value.split())


_UNTRUSTED_KEYS = _fields(
    "api_key authorization credential env environment password prompt rawPrompt secret secrets token transcript"
)
_POLICY_FIELDS = _fields(
    "schemaVersion policyId revision defaultLevel operations limits authority productionPromotionClaimed policyDigest"
)
_POLICY_OPERATION_FIELDS = _fields(
    "declaredLevel supported qualified effectiveLevel qualificationStatus hostOwnedPreAction"
)
_POLICY_LIMIT_FIELDS = _fields("maxEvents maxPayloadBytes maxChangedPaths maxAttestationAgeSeconds maxNonceBytes")
_POLICY_AUTHORITY_FIELDS = _fields("modelWritable settingsAutoEdited keysExternal providerIdentityUsed")
_REQUEST_FIELDS = _fields(
    "schemaVersion requestId adapterId host hostVersion operation runId taskId packageId planRevision planDigest "
    "lockDigest stateRevision actionDigest paths requestedLevel producerId nonce createdAt "
    "productionPromotionClaimed requestDigest"
)
_DECISION_FIELDS = _fields(
    "schemaVersion status requestDigest operation effectiveLevel hostActionAllowed authority blockers "
    "productionPromotionClaimed decisionDigest"
)
_EVENT_FIELDS = _fields(
    "schemaVersion eventId eventType status requestDigest operation producer nonce changedPaths outcome recordedAt "
    "productionPromotionClaimed eventDigest"
)
_ATTESTATION_FIELDS = _fields(
    "schemaVersion attestationId domain producerId adapterId hostVersion operation nonce issuedAt expiresAt planDigest "
    "lockDigest stateRevision actionDigest outcomeDigest keyId signature productionPromotionClaimed attestationDigest"
)
_QUALIFICATION_FIELDS = _fields(
    "schemaVersion status adapterId host hostVersion operation declaredLevel supportedLevel qualifiedLevel "
    "positiveEvidence "
    "negativeEvidence evidenceRefs blockers productionPromotionClaimed receiptDigest"
)
