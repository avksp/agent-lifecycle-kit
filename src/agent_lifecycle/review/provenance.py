"""Verify reviewer identity under an independently supplied public trust context."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.ed25519 import fingerprint, verify
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.reviewer_identity_schemas import (
    PROVENANCE_VALIDATION_V1,
    parse_reviewer_utc,
    validate_reviewer_attestation_shape,
    validate_reviewer_trust_root,
)
from agent_lifecycle.contracts.security_analysis_schemas import SECURITY_ANALYSIS_AUDIT_SCHEMA

_CONTEXT_FIELDS = {
    "trustRoot",
    "expectedTrustRootDigest",
    "expectedIssuerId",
    "expectedActorId",
    "expectedSessionId",
    "expectedPhase",
    "expectedAssignmentId",
    "expectedAssignmentDigest",
    "expectedSubjectDigest",
    "workerActorId",
    "workerSessionId",
    "referenceTime",
}
_PREFIX = b"agent-lifecycle-reviewer-attestation-v1\x00"
_NATIVE_PHASES = {
    "freeze": "plan-review",
    "task-review": "task-review",
    "implementation-audit": "task-review",
    "final-audit": "final-review",
}
_DECISION_PHASES = {**_NATIVE_PHASES, "final-implementation-audit": "final-review"}
_DERIVED_REPORT_FIELDS = {
    "implementation-audit": "reportDigest",
    "final-implementation-audit": "auditDigest",
    "final-audit": "completionSignalValidation",
}


def _identifier(value: Any) -> bool:
    return type(value) is str and 1 <= len(value.encode("utf-8")) <= 128


def _result(status: str, field: str | None = None, **digests: str | None) -> dict[str, Any]:
    code = "evidence-provenance-unsupported" if status == "UNSUPPORTED" else "evidence-provenance-unverified"
    return {
        "schemaVersion": PROVENANCE_VALIDATION_V1,
        "status": status,
        "guarantee": "ATTESTED" if status == "PASS" else "UNAVAILABLE",
        "attestationDigest": digests.get("attestationDigest"),
        "claimsDigest": digests.get("claimsDigest"),
        "trustRootDigest": digests.get("trustRootDigest"),
        "assignmentDigest": digests.get("assignmentDigest"),
        "subjectDigest": digests.get("subjectDigest"),
        "blockers": [] if status == "PASS" else [{"code": code, "field": field or "context"}],
    }


def _context(value: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    if type(value) is not dict or set(value) != _CONTEXT_FIELDS:
        raise LifecycleError("provenance-context-unavailable", "Trusted reviewer context is incomplete")
    root = validate_reviewer_trust_root(value["trustRoot"])
    root_digest = canonical_digest(root)
    if value["expectedTrustRootDigest"] != root_digest:
        raise LifecycleError("provenance-root-unavailable", "Reviewer trust root is not independently pinned")
    for field in ("expectedIssuerId", "expectedActorId", "expectedSessionId", "expectedPhase", "expectedAssignmentId"):
        if not _identifier(value[field]):
            raise LifecycleError("provenance-context-unavailable", f"Missing {field}")
    for field in ("expectedAssignmentDigest", "expectedSubjectDigest"):
        item = value[field]
        if type(item) is not str or len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item):
            raise LifecycleError("provenance-context-unavailable", f"Missing {field}")
    if value["expectedPhase"] not in {"plan-review", "task-review", "final-review"}:
        raise LifecycleError("provenance-context-unavailable", "Reviewer phase is unsupported")
    parse_reviewer_utc(value["referenceTime"])
    worker_actor, worker_session = value["workerActorId"], value["workerSessionId"]
    if (worker_actor is None) != (worker_session is None):
        raise LifecycleError("provenance-context-unavailable", "Incomplete worker identity")
    if worker_actor is None and value["expectedPhase"] != "plan-review":
        raise LifecycleError("provenance-context-unavailable", "Task or final review needs an actual author")
    if worker_actor is not None and (not _identifier(worker_actor) or not _identifier(worker_session)):
        raise LifecycleError("provenance-context-unavailable", "Worker identity is invalid")
    issuers = [issuer for issuer in root["authorizedIssuers"] if issuer["issuerId"] == value["expectedIssuerId"]]
    if len(issuers) != 1:
        raise LifecycleError("provenance-issuer-unavailable", "Expected issuer is absent from the pinned root")
    issuer = issuers[0]
    if issuer["fingerprint"] != fingerprint(bytes.fromhex(issuer["publicKeyHex"])):
        raise LifecycleError("provenance-root-unavailable", "Issuer fingerprint does not match its key")
    if value["expectedActorId"] not in issuer["actorIds"] or value["expectedPhase"] not in issuer["phases"]:
        raise LifecycleError("provenance-assignment-unavailable", "Issuer does not allow the expected actor and phase")
    return value, issuer, root_digest


def verify_reviewer_attestation(attestation: Any, *, trusted_context: Any) -> dict[str, Any]:
    """Return ATTESTED only for a fresh, exact, domain-separated issuer proof."""
    try:
        context, issuer, root_digest = _context(trusted_context)
    except (LifecycleError, TypeError, ValueError):
        return _result("UNSUPPORTED", "trustedContext")
    bound = {
        "trustRootDigest": root_digest,
        "assignmentDigest": context["expectedAssignmentDigest"],
        "subjectDigest": context["expectedSubjectDigest"],
    }
    if context["workerActorId"] == context["expectedActorId"] or (
        context["workerSessionId"] is not None and context["workerSessionId"] == context["expectedSessionId"]
    ):
        return _result("FAIL", "reviewerSeparation", **bound)
    try:
        proof = validate_reviewer_attestation_shape(attestation)
    except (LifecycleError, TypeError, ValueError):
        return _result("FAIL", "attestation", **bound)
    claims = proof["claims"]
    bound.update(attestationDigest=canonical_digest(proof), claimsDigest=canonical_digest(claims))
    expected = {
        "issuerId": context["expectedIssuerId"],
        "actorId": context["expectedActorId"],
        "sessionId": context["expectedSessionId"],
        "phase": context["expectedPhase"],
        "assignmentId": context["expectedAssignmentId"],
        "assignmentDigest": context["expectedAssignmentDigest"],
        "subjectDigest": context["expectedSubjectDigest"],
        "trustRootDigest": root_digest,
    }
    if any(claims[key] != value for key, value in expected.items()):
        return _result("FAIL", "claims", **bound)
    nonce = canonical_digest(
        {
            "domain": "agent-reviewer-challenge.v1",
            "phase": context["expectedPhase"],
            "assignmentDigest": context["expectedAssignmentDigest"],
            "subjectDigest": context["expectedSubjectDigest"],
            "actorId": context["expectedActorId"],
            "sessionId": context["expectedSessionId"],
            "trustRootDigest": root_digest,
        }
    )
    if claims["nonce"] != nonce:
        return _result("FAIL", "nonce", **bound)
    issued = parse_reviewer_utc(claims["issuedAt"])
    expires = parse_reviewer_utc(claims["expiresAt"])
    now = parse_reviewer_utc(context["referenceTime"])
    if not (issued <= now <= expires and timedelta(0) < expires - issued <= timedelta(seconds=300)):
        return _result("FAIL", "validity", **bound)
    if proof["signer"]["fingerprint"] != issuer["fingerprint"]:
        return _result("FAIL", "signer", **bound)
    signed_body = {key: value for key, value in proof.items() if key != "signature"}
    message = _PREFIX + canonical_bytes(signed_body)
    if not verify(bytes.fromhex(issuer["publicKeyHex"]), message, bytes.fromhex(proof["signature"])):
        return _result("FAIL", "signature", **bound)
    return _result("PASS", **bound)


def validate_native_reviewer_provenance(
    review: Any, *, native_phase: str, trusted_context: Any = None
) -> dict[str, Any]:
    """Refuse native ATTESTED claims until an operator-owned context route exists."""
    if type(native_phase) is not str or native_phase not in _NATIVE_PHASES or type(review) is not dict:
        return _result("FAIL", "nativePhase")
    supplied = review.get("reviewerProvenance")
    if supplied is not None and (
        type(supplied) is not dict
        or set(supplied) != {"guarantee", "attestation"}
        or type(supplied["guarantee"]) is not str
        or supplied["guarantee"] not in {"DECLARED", "ATTESTED"}
        or (supplied["guarantee"] == "DECLARED" and supplied["attestation"] is not None)
    ):
        return _result("FAIL", "reviewerProvenance")
    if trusted_context is not None:
        return _result("UNSUPPORTED", "trustedContext")
    if any(key in review for key in ("reviewerGuarantee", "reviewerAttestation", "provenanceValidation")):
        return _result("FAIL", "reviewerProvenance")
    reviewer = review.get("reviewer")
    if isinstance(reviewer, dict) and any(
        key in reviewer for key in ("guarantee", "attestation", "provenanceValidation")
    ):
        return _result("FAIL", "reviewerProvenance")
    if supplied is not None and supplied["guarantee"] == "ATTESTED":
        try:
            attestation = validate_reviewer_attestation_shape(supplied["attestation"])
        except (LifecycleError, TypeError, ValueError):
            return _result("FAIL", "attestation")
        if attestation["claims"]["phase"] != _NATIVE_PHASES[native_phase]:
            return _result("FAIL", "nativePhase")
    return _result("UNSUPPORTED", "trustedContext")


def reviewer_observed_at() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def reviewer_decision_context(
    policy: dict[str, Any],
    report: dict[str, Any],
    *,
    phase: str,
    lineage: dict[str, Any],
    author: tuple[Any, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Derive the signed subject from policy and actual effect-bearing inputs."""
    key = f"{phase}:{lineage['taskId']}" if "taskId" in lineage else phase
    assignment = policy["assignments"].get(key)
    if assignment is None or phase not in _DECISION_PHASES:
        raise LifecycleError("reviewer-assignment-required", "No frozen reviewer assignment for this decision")
    actor = report.get("reviewer" if phase in {"freeze", "task-review"} else "auditor")
    if (
        author != (assignment["authorActorId"], assignment["authorSessionId"])
        or not isinstance(actor, dict)
        or (actor.get("id"), actor.get("runId"))
        != (assignment["reviewerActorId"], assignment["reviewerSessionId"])
    ):
        raise LifecycleError("reviewer-assignment-mismatch", "Decision actors do not match the frozen assignment")
    issuer = next(
        (entry for entry in policy["trustRoot"]["authorizedIssuers"] if entry["issuerId"] == assignment["issuerId"]),
        None,
    )
    if issuer is None or issuer["fingerprint"] == assignment["authorFingerprint"]:
        raise LifecycleError("reviewer-key-separation-required", "An independent assigned reviewer key is required")
    if not (
        parse_reviewer_utc(assignment["validFrom"])
        <= parse_reviewer_utc(observed_at)
        < parse_reviewer_utc(assignment["expiresAt"])
    ):
        raise LifecycleError("reviewer-key-expired", "Reviewer key is outside its assigned validity interval")
    assignment_digest = canonical_digest(
        {
            "schemaVersion": "agent-reviewer-decision-assignment.v1",
            "phase": phase,
            "lineage": lineage,
            "assignment": assignment,
        }
    )
    excluded = {"reviewerProvenance", _DERIVED_REPORT_FIELDS.get(phase)}
    if phase == "implementation-audit" and report.get("schemaVersion") == SECURITY_ANALYSIS_AUDIT_SCHEMA:
        excluded.add("auditDigest")
    subject = canonical_digest(
        {
            "schemaVersion": "agent-reviewer-decision-subject.v1",
            "assignmentDigest": assignment_digest,
            "report": {name: value for name, value in report.items() if name not in excluded},
        }
    )
    return {
        "trustRoot": policy["trustRoot"],
        "expectedTrustRootDigest": policy["trustRootDigest"],
        "expectedIssuerId": assignment["issuerId"],
        "expectedActorId": assignment["reviewerActorId"],
        "expectedSessionId": assignment["reviewerSessionId"],
        "expectedPhase": _DECISION_PHASES[phase],
        "expectedAssignmentId": f"decision:{assignment_digest}",
        "expectedAssignmentDigest": assignment_digest,
        "expectedSubjectDigest": subject,
        "workerActorId": assignment["authorActorId"],
        "workerSessionId": assignment["authorSessionId"],
        "referenceTime": observed_at,
    }


def verify_reviewer_decision(
    policy: dict[str, Any],
    report: dict[str, Any],
    *,
    phase: str,
    lineage: dict[str, Any],
    author: tuple[Any, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Authenticate one native decision and return an archival admission receipt."""
    envelope = report.get("reviewerProvenance")
    if not isinstance(envelope, dict) or set(envelope) != {"guarantee", "attestation"} or (
        envelope["guarantee"] != "ATTESTED"
    ):
        raise LifecycleError("reviewer-attestation-required", "This decision requires an exact signed review")
    context = reviewer_decision_context(policy, report, phase=phase, lineage=lineage, author=author, observed_at=observed_at)
    validation = verify_reviewer_attestation(envelope["attestation"], trusted_context=context)
    if validation["status"] != "PASS":
        raise LifecycleError("reviewer-attestation-refused", "The signed reviewer decision did not verify", validation)
    return {
        "phase": phase,
        "observedAt": observed_at,
        "reportDigest": canonical_digest(report),
        "attestationDigest": validation["attestationDigest"],
        "subjectDigest": validation["subjectDigest"],
    }


__all__ = [
    "reviewer_decision_context",
    "reviewer_observed_at",
    "validate_native_reviewer_provenance",
    "verify_reviewer_attestation",
    "verify_reviewer_decision",
]
