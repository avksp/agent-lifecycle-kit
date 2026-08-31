"""Build and validate bounded, non-authoritative cross-phase packets."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, NoReturn

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.phase_packet_schemas import (
    IMPLEMENTATION_PAYLOAD_SCHEMA,
    PHASE_PACKET_SCHEMA,
    PLANNING_HANDOFF_PAYLOAD_SCHEMA,
    REMEDIATION_PAYLOAD_SCHEMA,
    TASK_AUDIT_PAYLOAD_SCHEMA,
)
from agent_lifecycle.contracts.redaction import redact_value

MAX_PHASE_PACKET_BYTES = 64 * 1024

FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "rawTranscript",
        "transcript",
        "conversation",
        "message",
        "messages",
        "chatHistory",
        "systemPrompt",
        "developerPrompt",
        "userPrompt",
        "prompt",
        "secret",
        "secrets",
        "apiKey",
        "apiToken",
        "accessToken",
        "refreshToken",
        "password",
        "credential",
        "credentials",
        "authorization",
        "cookie",
        "promptAuthority",
        "toolAuthority",
        "freezeAuthority",
        "acceptanceAuthority",
        "implementationAuthority",
        "implementationAuthorized",
        "proofAuthority",
        "productionPromotionClaimed",
    }
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PURPOSE_SCHEMAS = {
    "PLANNING_HANDOFF": PLANNING_HANDOFF_PAYLOAD_SCHEMA,
    "IMPLEMENTATION": IMPLEMENTATION_PAYLOAD_SCHEMA,
    "TASK_AUDIT": TASK_AUDIT_PAYLOAD_SCHEMA,
    "REMEDIATION": REMEDIATION_PAYLOAD_SCHEMA,
}

_ACCEPTANCE_KEYS = {
    "id",
    "requirementIds",
    "evidenceIds",
    "independentEvidenceIds",
    "independence",
    "statement",
    "description",
    "source",
    "priority",
}
_EVIDENCE_KEYS = {"id", "description", "source", "validation", "artifactPath", "required"}
_WORKSTREAM_KEYS = {
    "id",
    "dependsOn",
    "writes",
    "readOnly",
    "forbiddenWrites",
    "acceptanceCriteria",
    "evidenceRequirements",
    "activeBlockerIds",
}


def build_phase_packet(
    *,
    purpose: str,
    payload: dict[str, Any],
    plan_digest: str,
    plan_lock_digest: str,
    state_revision: int | None,
    source_revision: str,
    write_scope_digest: str,
    acceptance_digest: str,
    evidence_digest: str,
    active_blocker_ids: list[str],
    max_context_bytes: int = MAX_PHASE_PACKET_BYTES,
) -> dict[str, Any]:
    """Build one closed packet, redacting unsafe string values before digesting."""

    _require_context_bound(payload, max_context_bytes, "phase packet payload")
    _reject_forbidden_keys(payload)
    redacted_payload, _changed = redact_value(deepcopy(payload))
    if not isinstance(redacted_payload, dict):
        _missing("payload must be an object")
    body = {
        "schemaVersion": PHASE_PACKET_SCHEMA,
        "purpose": purpose,
        "planDigest": plan_digest,
        "planLockDigest": plan_lock_digest,
        "stateRevision": state_revision,
        "sourceRevision": source_revision,
        "writeScopeDigest": write_scope_digest,
        "acceptanceDigest": acceptance_digest,
        "evidenceDigest": evidence_digest,
        "activeBlockerIds": _canonical_strings(active_blocker_ids, "activeBlockerIds"),
        "payload": _normalize_payload(purpose, redacted_payload),
        "implementationAuthorized": False,
        "proofAuthority": "none",
        "productionPromotionClaimed": False,
    }
    packet = {**body, "packetDigest": canonical_digest(body)}
    validate_phase_packet(packet, max_context_bytes=max_context_bytes)
    return packet


def validate_phase_packet(
    packet: dict[str, Any],
    *,
    max_context_bytes: int = MAX_PHASE_PACKET_BYTES,
) -> dict[str, Any]:
    """Validate exact shape, safety, lineage and digest of a phase packet."""

    _require_context_bound(packet, max_context_bytes, "phase packet")
    expected_keys = {
        "schemaVersion",
        "purpose",
        "planDigest",
        "planLockDigest",
        "stateRevision",
        "sourceRevision",
        "writeScopeDigest",
        "acceptanceDigest",
        "evidenceDigest",
        "activeBlockerIds",
        "payload",
        "implementationAuthorized",
        "proofAuthority",
        "productionPromotionClaimed",
        "packetDigest",
    }
    _closed(packet, expected_keys, expected_keys, "phase packet")
    if packet.get("schemaVersion") != PHASE_PACKET_SCHEMA:
        _missing("phase packet schemaVersion is invalid")
    purpose = packet.get("purpose")
    if purpose not in _PURPOSE_SCHEMAS:
        _missing("phase packet purpose is invalid")
    for field in (
        "planDigest",
        "planLockDigest",
        "writeScopeDigest",
        "acceptanceDigest",
        "evidenceDigest",
        "packetDigest",
    ):
        _require_digest(packet.get(field), field)
    state_revision = packet.get("stateRevision")
    if purpose == "PLANNING_HANDOFF":
        if state_revision is not None:
            _missing("planning handoff stateRevision must be null")
    elif not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
        _missing("phase packet stateRevision must be positive")
    if not isinstance(packet.get("sourceRevision"), str) or not packet["sourceRevision"]:
        _missing("phase packet sourceRevision is required")
    if packet.get("implementationAuthorized") is not False:
        _forbidden("phase packet cannot authorize implementation")
    if packet.get("proofAuthority") != "none":
        _forbidden("phase packet cannot claim proof authority")
    if packet.get("productionPromotionClaimed") is not False:
        _forbidden("phase packet cannot claim production promotion")
    blockers = _canonical_strings(packet.get("activeBlockerIds"), "activeBlockerIds")
    if blockers != packet["activeBlockerIds"]:
        _missing("phase packet activeBlockerIds must be canonical")
    payload = packet.get("payload")
    if not isinstance(payload, dict):
        _missing("phase packet payload must be an object")
    _reject_forbidden_keys(payload)
    redacted, changed = redact_value(payload)
    if changed or redacted != payload:
        _forbidden("phase packet payload contains unredacted sensitive content")
    normalized = _normalize_payload(purpose, payload)
    if normalized != payload:
        _missing("phase packet payload lists must be canonical")
    if payload.get("activeBlockerIds") is not None and payload.get("activeBlockerIds") != blockers:
        _missing("phase packet blocker lineage does not match its payload")
    body = {key: value for key, value in packet.items() if key != "packetDigest"}
    if packet["packetDigest"] != canonical_digest(body):
        _missing("phase packet digest mismatch")
    return packet


def _normalize_payload(purpose: str, payload: dict[str, Any]) -> dict[str, Any]:
    schema = _PURPOSE_SCHEMAS.get(purpose)
    if schema is None or payload.get("schemaVersion") != schema:
        _missing("phase packet payload schema does not match purpose")
    if purpose == "PLANNING_HANDOFF":
        _closed(
            payload,
            {"schemaVersion", "workstreams", "dependencyEdges"},
            {"schemaVersion", "workstreams", "dependencyEdges"},
            "planning handoff payload",
        )
        workstreams = _objects(payload.get("workstreams"), "workstreams")
        edges = _objects(payload.get("dependencyEdges"), "dependencyEdges")
        normalized_workstreams = [_normalize_workstream(item) for item in workstreams]
        normalized_edges = []
        for edge in edges:
            _closed(edge, {"from", "to"}, {"from", "to"}, "dependency edge")
            normalized_edges.append(
                {
                    "from": _string(edge.get("from"), "dependency edge from"),
                    "to": _string(edge.get("to"), "dependency edge to"),
                }
            )
        return {
            "schemaVersion": schema,
            "workstreams": sorted(normalized_workstreams, key=lambda item: item["id"]),
            "dependencyEdges": sorted(normalized_edges, key=lambda item: (item["from"], item["to"])),
        }
    if purpose == "IMPLEMENTATION":
        keys = {
            "schemaVersion",
            "taskId",
            "attempt",
            "taskPacketDigest",
            "writes",
            "readOnly",
            "forbiddenWrites",
            "acceptanceCriteria",
            "evidenceRequirements",
            "activeBlockerIds",
        }
        _closed(payload, keys, keys, "implementation payload")
        return {
            "schemaVersion": schema,
            "taskId": _string(payload.get("taskId"), "taskId"),
            "attempt": _positive_int(payload.get("attempt"), "attempt"),
            "taskPacketDigest": _digest(payload.get("taskPacketDigest"), "taskPacketDigest"),
            "writes": _canonical_strings(payload.get("writes"), "writes"),
            "readOnly": _canonical_strings(payload.get("readOnly"), "readOnly"),
            "forbiddenWrites": _canonical_strings(payload.get("forbiddenWrites"), "forbiddenWrites"),
            "acceptanceCriteria": _normalize_acceptance(payload.get("acceptanceCriteria")),
            "evidenceRequirements": _normalize_evidence(payload.get("evidenceRequirements")),
            "activeBlockerIds": _canonical_strings(payload.get("activeBlockerIds"), "activeBlockerIds"),
        }
    if purpose == "TASK_AUDIT":
        keys = {
            "schemaVersion",
            "taskId",
            "attempt",
            "resultDigest",
            "changeSetDigest",
            "changedPaths",
            "writes",
            "readOnly",
            "forbiddenWrites",
            "reviewRequirements",
            "acceptanceCriteria",
            "evidenceReferences",
            "activeBlockerIds",
        }
        _closed(payload, keys, keys, "task audit payload")
        review = payload.get("reviewRequirements")
        if not isinstance(review, dict):
            _missing("reviewRequirements must be an object")
        review_keys = {"independentRequired", "minimumVerdict", "requiredReviewerIds"}
        _closed(review, review_keys, review_keys, "review requirements")
        independent = review.get("independentRequired")
        if not isinstance(independent, bool):
            _missing("independentRequired must be boolean")
        return {
            "schemaVersion": schema,
            "taskId": _string(payload.get("taskId"), "taskId"),
            "attempt": _positive_int(payload.get("attempt"), "attempt"),
            "resultDigest": _digest(payload.get("resultDigest"), "resultDigest"),
            "changeSetDigest": _digest(payload.get("changeSetDigest"), "changeSetDigest"),
            "changedPaths": _canonical_strings(payload.get("changedPaths"), "changedPaths"),
            "writes": _canonical_strings(payload.get("writes"), "writes"),
            "readOnly": _canonical_strings(payload.get("readOnly"), "readOnly"),
            "forbiddenWrites": _canonical_strings(payload.get("forbiddenWrites"), "forbiddenWrites"),
            "reviewRequirements": {
                "independentRequired": independent,
                "minimumVerdict": _string(review.get("minimumVerdict"), "minimumVerdict"),
                "requiredReviewerIds": _canonical_strings(review.get("requiredReviewerIds"), "requiredReviewerIds"),
            },
            "acceptanceCriteria": _normalize_acceptance(payload.get("acceptanceCriteria")),
            "evidenceReferences": _canonical_strings(payload.get("evidenceReferences"), "evidenceReferences"),
            "activeBlockerIds": _canonical_strings(payload.get("activeBlockerIds"), "activeBlockerIds"),
        }
    keys = {
        "schemaVersion",
        "taskId",
        "attempt",
        "priorResultDigest",
        "priorReviewDigest",
        "changedPaths",
        "openFindingIds",
        "remainingAttempts",
        "writes",
        "readOnly",
        "forbiddenWrites",
        "acceptanceCriteria",
        "evidenceRequirements",
        "activeBlockerIds",
    }
    _closed(payload, keys, keys, "remediation payload")
    return {
        "schemaVersion": schema,
        "taskId": _string(payload.get("taskId"), "taskId"),
        "attempt": _positive_int(payload.get("attempt"), "attempt"),
        "priorResultDigest": _digest(payload.get("priorResultDigest"), "priorResultDigest"),
        "priorReviewDigest": _digest(payload.get("priorReviewDigest"), "priorReviewDigest"),
        "changedPaths": _canonical_strings(payload.get("changedPaths"), "changedPaths"),
        "openFindingIds": _canonical_strings(payload.get("openFindingIds"), "openFindingIds"),
        "remainingAttempts": _positive_int(payload.get("remainingAttempts"), "remainingAttempts"),
        "writes": _canonical_strings(payload.get("writes"), "writes"),
        "readOnly": _canonical_strings(payload.get("readOnly"), "readOnly"),
        "forbiddenWrites": _canonical_strings(payload.get("forbiddenWrites"), "forbiddenWrites"),
        "acceptanceCriteria": _normalize_acceptance(payload.get("acceptanceCriteria")),
        "evidenceRequirements": _normalize_evidence(payload.get("evidenceRequirements")),
        "activeBlockerIds": _canonical_strings(payload.get("activeBlockerIds"), "activeBlockerIds"),
    }


def _normalize_workstream(value: dict[str, Any]) -> dict[str, Any]:
    _closed(value, _WORKSTREAM_KEYS, _WORKSTREAM_KEYS, "workstream")
    return {
        "id": _string(value.get("id"), "workstream id"),
        "dependsOn": _canonical_strings(value.get("dependsOn"), "dependsOn"),
        "writes": _canonical_strings(value.get("writes"), "writes"),
        "readOnly": _canonical_strings(value.get("readOnly"), "readOnly"),
        "forbiddenWrites": _canonical_strings(value.get("forbiddenWrites"), "forbiddenWrites"),
        "acceptanceCriteria": _normalize_acceptance(value.get("acceptanceCriteria")),
        "evidenceRequirements": _normalize_evidence(value.get("evidenceRequirements")),
        "activeBlockerIds": _canonical_strings(value.get("activeBlockerIds"), "activeBlockerIds"),
    }


def _normalize_acceptance(value: Any) -> list[dict[str, Any]]:
    items = _objects(value, "acceptanceCriteria")
    normalized = []
    for item in items:
        _closed(item, {"id"}, _ACCEPTANCE_KEYS, "acceptance criterion")
        result: dict[str, Any] = {"id": _string(item.get("id"), "acceptance criterion id")}
        for key in ("requirementIds", "evidenceIds", "independentEvidenceIds"):
            if key in item:
                result[key] = _canonical_strings(item[key], key)
        for key in ("independence", "statement", "description", "source", "priority"):
            if key in item:
                if key in {"statement", "description"} and not isinstance(item[key], str):
                    _missing(f"acceptance criterion {key} must be a string")
                result[key] = deepcopy(item[key])
        normalized.append(result)
    return sorted(normalized, key=lambda item: item["id"])


def _normalize_evidence(value: Any) -> list[dict[str, Any]]:
    items = _objects(value, "evidenceRequirements")
    normalized = []
    for item in items:
        _closed(item, {"id"}, _EVIDENCE_KEYS, "evidence requirement")
        result: dict[str, Any] = {"id": _string(item.get("id"), "evidence requirement id")}
        for key in ("description", "source", "validation", "artifactPath", "required"):
            if key in item:
                if key in {"description", "artifactPath"} and not isinstance(item[key], str):
                    _missing(f"evidence requirement {key} must be a string")
                if key == "required" and not isinstance(item[key], bool):
                    _missing("evidence requirement required must be boolean")
                result[key] = deepcopy(item[key])
        normalized.append(result)
    return sorted(normalized, key=lambda item: item["id"])


def _reject_forbidden_keys(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _forbidden("phase packet payload keys must be strings")
            if key in FORBIDDEN_PAYLOAD_KEYS:
                _forbidden("phase packet payload contains a forbidden key", path="/".join((*path, key)))
            _reject_forbidden_keys(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, (*path, str(index)))


def _require_context_bound(value: Any, max_context_bytes: int, label: str) -> None:
    if (
        not isinstance(max_context_bytes, int)
        or isinstance(max_context_bytes, bool)
        or not 1 <= max_context_bytes <= MAX_PHASE_PACKET_BYTES
    ):
        _limit("phase packet context limit is invalid")
    try:
        byte_count = len(canonical_bytes(value))
    except (LifecycleError, TypeError):
        _missing(f"{label} must be JSON-compatible")
    if byte_count > max_context_bytes:
        _limit(f"{label} exceeds its rendered context limit")


def _closed(value: Any, required: set[str], allowed: set[str], label: str) -> None:
    if not isinstance(value, dict):
        _missing(f"{label} must be an object")
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        _missing(f"{label} has missing or unsupported fields", missing=missing, extra=extra)


def _objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        _missing(f"{label} must be an object list")
    return value


def _canonical_strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        _missing(f"{label} must be a string list")
    return sorted(set(value))


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        _missing(f"{label} is required")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        _missing(f"{label} must be a positive integer")
    return value


def _require_digest(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _missing(f"{label} must be a canonical digest")


def _digest(value: Any, label: str) -> str:
    _require_digest(value, label)
    return value


def _missing(message: str, **details: Any) -> NoReturn:
    raise LifecycleError("phase-packet-required-fact-missing", message, details)


def _forbidden(message: str, **details: Any) -> NoReturn:
    raise LifecycleError("phase-packet-forbidden-content", message, details)


def _limit(message: str) -> NoReturn:
    raise LifecycleError("phase-packet-context-limit-exceeded", message)


__all__ = [
    "FORBIDDEN_PAYLOAD_KEYS",
    "MAX_PHASE_PACKET_BYTES",
    "build_phase_packet",
    "validate_phase_packet",
]
