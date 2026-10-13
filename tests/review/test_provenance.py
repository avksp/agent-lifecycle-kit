"""Signed reviewer proof is bound to independently selected identity and subject."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.reviewer_identity_schemas import ATTESTATION_V1, CLAIMS_V1, TRUST_ROOT_V1
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.neutrality.ed25519 import fingerprint, publickey_from_seed, sign
from agent_lifecycle.review.provenance import validate_native_reviewer_provenance, verify_reviewer_attestation

SEED = bytes(range(32))
PREFIX = b"agent-lifecycle-reviewer-attestation-v1\x00"
FIXTURE = Path(__file__).resolve().parent / "fixtures/reviewer_provenance.v1.json"


def _context() -> dict:
    public_key = publickey_from_seed(SEED)
    root = {
        "schemaVersion": TRUST_ROOT_V1, "revision": 1,
        "authorizedIssuers": [{
            "issuerId": "issuer", "fingerprint": fingerprint(public_key),
            "publicKeyHex": public_key.hex(), "actorIds": ["reviewer"],
            "phases": ["task-review"],
        }],
    }
    return {
        "trustRoot": root, "expectedTrustRootDigest": canonical_digest(root),
        "expectedIssuerId": "issuer", "expectedActorId": "reviewer",
        "expectedSessionId": "reviewer-session", "expectedPhase": "task-review",
        "expectedAssignmentId": "assignment", "expectedAssignmentDigest": "a" * 64,
        "expectedSubjectDigest": "b" * 64,
        "workerActorId": "worker", "workerSessionId": "worker-session",
        "referenceTime": "2026-09-23T02:00:00Z",
    }


def _attestation(context: dict) -> dict:
    claims = {
        "schemaVersion": CLAIMS_V1,
        "issuerId": context["expectedIssuerId"], "actorId": context["expectedActorId"],
        "sessionId": context["expectedSessionId"], "phase": context["expectedPhase"],
        "assignmentId": context["expectedAssignmentId"],
        "assignmentDigest": context["expectedAssignmentDigest"],
        "subjectDigest": context["expectedSubjectDigest"],
        "trustRootDigest": context["expectedTrustRootDigest"],
        "issuedAt": "2026-09-23T01:59:00Z", "expiresAt": "2026-09-23T02:04:00Z",
    }
    claims["nonce"] = canonical_digest({
        "domain": "agent-reviewer-challenge.v1", "phase": claims["phase"],
        "assignmentDigest": claims["assignmentDigest"], "subjectDigest": claims["subjectDigest"],
        "actorId": claims["actorId"], "sessionId": claims["sessionId"],
        "trustRootDigest": claims["trustRootDigest"],
    })
    body = {
        "schemaVersion": ATTESTATION_V1, "claims": claims,
        "signer": {"algorithm": "Ed25519", "fingerprint": context["trustRoot"]["authorizedIssuers"][0]["fingerprint"]},
    }
    return {**body, "signature": sign(SEED, PREFIX + canonical_bytes(body)).hex()}


class ReviewerProvenanceTests(unittest.TestCase):
    def test_valid_pinned_test_issuer_and_exact_assignment_pass(self) -> None:
        context = _context()
        self.assertEqual(get_schema(TRUST_ROOT_V1)["$id"], TRUST_ROOT_V1)
        self.assertEqual(get_schema(ATTESTATION_V1)["$id"], ATTESTATION_V1)
        result = verify_reviewer_attestation(_attestation(context), trusted_context=context)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["guarantee"], "ATTESTED")
        self.assertEqual(result["blockers"], [])
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertFalse(fixture["nativeRouteQualified"])
        self.assertEqual(
            verify_reviewer_attestation(fixture["attestation"], trusted_context=fixture["context"])["status"],
            fixture["expectedPureVerifierStatus"],
        )

    def test_pinned_identity_issuer_cannot_attest_fresh_claims(self) -> None:
        context = _context()
        identity = (1).to_bytes(32, "little")
        issuer = context["trustRoot"]["authorizedIssuers"][0]
        issuer.update(publicKeyHex=identity.hex(), fingerprint=fingerprint(identity))
        context["expectedTrustRootDigest"] = canonical_digest(context["trustRoot"])
        forged = _attestation(context)
        forged["signature"] = (identity + bytes(32)).hex()
        result = verify_reviewer_attestation(forged, trusted_context=context)
        self.assertEqual(result["status"], "FAIL")
        self.assertNotEqual(result["guarantee"], "ATTESTED")
        native = validate_native_reviewer_provenance(
            {"reviewer": {"id": "reviewer", "independent": True},
             "reviewerProvenance": {"guarantee": "ATTESTED", "attestation": forged}},
            trusted_context=context, native_phase="task-review",
        )
        self.assertEqual(native["status"], "UNSUPPORTED")

    def test_wrong_subject_signature_and_domain_cannot_claim_attested(self) -> None:
        context = _context()
        valid = _attestation(context)
        wrong_subject = {**context, "expectedSubjectDigest": "c" * 64}
        self.assertEqual(verify_reviewer_attestation(valid, trusted_context=wrong_subject)["status"], "FAIL")
        tampered = copy.deepcopy(valid)
        tampered["signature"] = "0" * 128
        self.assertEqual(verify_reviewer_attestation(tampered, trusted_context=context)["status"], "FAIL")
        wrong_domain = copy.deepcopy(valid)
        body = {key: value for key, value in valid.items() if key != "signature"}
        wrong_domain["signature"] = sign(SEED, b"neutrality\x00" + canonical_bytes(body)).hex()
        self.assertEqual(verify_reviewer_attestation(wrong_domain, trusted_context=context)["status"], "FAIL")

    def test_expiry_self_review_and_unpinned_root_fail_closed(self) -> None:
        context = _context()
        proof = _attestation(context)
        self.assertEqual(verify_reviewer_attestation(proof, trusted_context={**context, "referenceTime": "2026-09-23T02:04:01Z"})["status"], "FAIL")
        self.assertEqual(verify_reviewer_attestation(proof, trusted_context={**context, "workerSessionId": "reviewer-session"})["status"], "FAIL")
        unpinned = {**context, "expectedTrustRootDigest": "0" * 64}
        result = verify_reviewer_attestation(proof, trusted_context=unpinned)
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertEqual(result["guarantee"], "UNAVAILABLE")
        self.assertIsNone(result["attestationDigest"])
        self.assertEqual(verify_reviewer_attestation(proof, trusted_context=None)["status"], "UNSUPPORTED")

    def test_native_route_cannot_promote_report_selected_proof(self) -> None:
        context = _context()
        proof = _attestation(context)
        ordinary = {"reviewer": {"id": "reviewer", "independent": True}}
        self.assertEqual(validate_native_reviewer_provenance(ordinary, native_phase="task-review")["status"], "UNSUPPORTED")
        asserted = {**ordinary, "reviewerProvenance": {"guarantee": "ATTESTED", "attestation": proof}}
        result = validate_native_reviewer_provenance(asserted, native_phase="task-review")
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertEqual(result["guarantee"], "UNAVAILABLE")
        self.assertEqual(validate_native_reviewer_provenance(asserted, native_phase="freeze")["status"], "FAIL")
        self.assertEqual(validate_native_reviewer_provenance(asserted, native_phase="bogus")["status"], "FAIL")
        self.assertEqual(validate_native_reviewer_provenance(asserted, native_phase="task-review", trusted_context=context)["status"], "UNSUPPORTED")
        stripped = {**ordinary, "reviewerProvenance": {"guarantee": "ATTESTED", "attestation": None}}
        self.assertEqual(validate_native_reviewer_provenance(stripped, native_phase="task-review")["status"], "FAIL")
        imported = {**ordinary, "provenanceValidation": {"status": "PASS", "guarantee": "ATTESTED"}}
        self.assertEqual(validate_native_reviewer_provenance(imported, native_phase="task-review")["status"], "FAIL")
        malformed = {**ordinary, "reviewerProvenance": {"guarantee": [], "attestation": None}}
        self.assertEqual(validate_native_reviewer_provenance(malformed, native_phase="task-review")["status"], "FAIL")
