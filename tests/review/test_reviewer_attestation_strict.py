"""Exact native reviewer subjects and synthetic Ed25519 approval proofs."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest import TestCase

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.reviewer_identity_schemas import (
    REVIEWER_ATTESTATION_POLICY_V1,
    parse_reviewer_utc,
    validate_reviewer_attestation_policy,
)
from agent_lifecycle.neutrality.ed25519 import sign
from agent_lifecycle.review.provenance import reviewer_decision_context, verify_reviewer_decision
from tests.review.test_provenance import PREFIX, SEED, _attestation, _context

OBSERVED = "2026-11-17T19:00:00Z"
WORKER = ("worker", "worker-session")
REVIEWER = {"id": "reviewer", "runId": "reviewer-session", "surface": "fixture", "independent": True}


def policy_for(*roles: str, author: tuple[str, str] = WORKER) -> dict:
    root = _context()["trustRoot"]
    root["authorizedIssuers"][0]["phases"] = ["plan-review", "task-review", "final-review"]
    return {
        "schemaVersion": REVIEWER_ATTESTATION_POLICY_V1,
        "mode": "required",
        "trustRoot": root,
        "trustRootDigest": canonical_digest(root),
        "assignments": {
            role: {
                "issuerId": "issuer",
                "reviewerActorId": REVIEWER["id"],
                "reviewerSessionId": REVIEWER["runId"],
                "authorActorId": author[0],
                "authorSessionId": author[1],
                "authorFingerprint": "ed25519:" + "7" * 64,
                "validFrom": "2000-01-01T00:00:00Z",
                "expiresAt": "2099-01-01T00:00:00Z",
            }
            for role in roles
        },
    }


def attest(policy: dict, report: dict, *, phase: str, lineage: dict, author=WORKER, observed=OBSERVED) -> dict:
    context = reviewer_decision_context(policy, report, phase=phase, lineage=lineage, author=author, observed_at=observed)
    proof = _attestation(context)
    time = parse_reviewer_utc(observed)
    proof["claims"]["issuedAt"] = (time - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    proof["claims"]["expiresAt"] = (time + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {key: value for key, value in proof.items() if key != "signature"}
    proof["signature"] = sign(SEED, PREFIX + canonical_bytes(body)).hex()
    return {**report, "reviewerProvenance": {"guarantee": "ATTESTED", "attestation": proof}}


class StrictReviewerDecisionTests(TestCase):
    def setUp(self) -> None:
        self.policy = policy_for("task-review:task", "implementation-audit:task")
        validate_reviewer_attestation_policy(self.policy)
        self.lineage = {"taskId": "task", "planDigest": "a" * 64, "runId": "strict", "attempt": 1}
        report = {"reviewer": REVIEWER, "auditor": REVIEWER, "verdict": "ACCEPTED", "findings": []}
        self.report = attest(self.policy, report, phase="task-review", lineage=self.lineage)

    def verify(self, *, policy=None, report=None, lineage=None, author=WORKER, observed=OBSERVED, phase="task-review"):
        return verify_reviewer_decision(
            self.policy if policy is None else policy, self.report if report is None else report,
            phase=phase, lineage=self.lineage if lineage is None else lineage, author=author, observed_at=observed,
        )

    def test_exact_decision_uses_observed_time_and_preserves_exact_proof_identity(self) -> None:
        admission = self.verify()
        self.assertEqual(admission["observedAt"], OBSERVED)
        self.assertEqual(admission["reportDigest"], canonical_digest(self.report))

    def test_replayed_attempt_or_phase_and_changed_verdict_refuse(self) -> None:
        for kwargs in (
            {"report": {**self.report, "verdict": "REWORK"}},
            {"lineage": {**self.lineage, "attempt": 2}},
            {"phase": "implementation-audit"},
            {"author": ("other-worker", WORKER[1])},
        ):
            with self.subTest(fields=list(kwargs)), self.assertRaises(LifecycleError):
                self.verify(**kwargs)

    def test_missing_expired_or_wrong_signer_refuse(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "requires an exact signed review"):
            self.verify(report={"reviewer": REVIEWER, "verdict": "ACCEPTED"})
        with self.assertRaisesRegex(LifecycleError, "did not verify"):
            self.verify(observed="2026-11-17T19:01:00Z")
        policy = deepcopy(self.policy)
        policy["assignments"]["task-review:task"]["issuerId"] = "absent"
        with self.assertRaisesRegex(LifecycleError, "independent assigned reviewer key"):
            self.verify(policy=policy)

    def test_same_author_key_and_expired_key_refuse_despite_distinct_actor_names(self) -> None:
        policy = deepcopy(self.policy)
        assignment = policy["assignments"]["task-review:task"]
        assignment["authorFingerprint"] = policy["trustRoot"]["authorizedIssuers"][0]["fingerprint"]
        with self.assertRaisesRegex(LifecycleError, "independent assigned reviewer key"):
            self.verify(policy=policy)
        assignment["authorFingerprint"] = "ed25519:" + "7" * 64
        assignment["expiresAt"] = OBSERVED
        with self.assertRaisesRegex(LifecycleError, "assigned validity"):
            self.verify(policy=policy)

    def test_unpinned_public_root_refuses_before_decision(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "trust root pin"):
            validate_reviewer_attestation_policy({**self.policy, "trustRootDigest": "0" * 64})
