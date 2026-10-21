"""Review envelope checks; these do not attest reviewer identity or host proof."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.neutrality.ed25519 import sign
from agent_lifecycle.review.provenance import validate_native_reviewer_provenance, verify_reviewer_attestation
from agent_lifecycle.review.validation import (
    build_review_impact_graph,
    derive_delta_selection,
    review_impact_closure,
    validate_bound_plan_review,
    validate_independent_review,
    validate_review_composition,
)
from tests.review import refresh_candidate, synthetic_case, synthetic_chain
from tests.review.test_provenance import PREFIX, SEED, _attestation, _context


class IndependentReviewValidationTests(unittest.TestCase):
    def test_declared_reviews_preserve_behavior_and_authority_claims_refuse(self):
        for claim in ({}, {"reviewerProvenance": {"guarantee": "DECLARED", "attestation": None}}):
            with self.subTest(claim=claim):
                self.assertEqual(validate_independent_review({**self.review(), **claim})["verdict"], "ACCEPTED")
        context = _context()
        context["expectedPhase"] = "plan-review"
        context["trustRoot"]["authorizedIssuers"][0]["phases"] = ["plan-review"]
        context["expectedTrustRootDigest"] = canonical_digest(context["trustRoot"])
        claims = [
            {"reviewerProvenance": None},
            {"reviewerProvenance": {}},
            {"reviewerProvenance": {"guarantee": "ATTESTED", "attestation": None}},
            {"reviewerProvenance": {"guarantee": "ATTESTED", "attestation": _attestation(context)}},
            {"provenanceValidation": {"status": "PASS", "guarantee": "ATTESTED"}},
            {"reviewerGuarantee": "ATTESTED"},
            {"reviewerAttestation": _attestation(context)},
            {"reviewer": {"id": "reviewer", "independent": True, "guarantee": "ATTESTED"}},
        ]
        for index, claim in enumerate(claims):
            value = {**self.review(), **claim}
            original = copy.deepcopy(value)
            with self.subTest(index=index), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertIn(caught.exception.code, {"review-provenance-invalid", "review-provenance-unsupported"})
            self.assertEqual(value, original)

    @staticmethod
    def review() -> dict:
        return {"reviewer": {"id": "independent-reviewer", "independent": True}, "verdict": "ACCEPTED", "findings": []}

    def test_positive_verdicts_allow_closed_blockers_and_open_low_findings(self):
        for verdict in ("READY_TO_FREEZE", "ACCEPTED"):
            value = self.review()
            value["verdict"] = verdict
            value["findings"] = [
                {"id": "closed", "severity": "HIGH", "status": "closed"},
                {"id": "low", "severity": "LOW", "status": "open"},
            ]
            with self.subTest(verdict=verdict):
                self.assertEqual(
                    validate_independent_review(value),
                    {"schemaVersion": "agent-review-validation.v1", "verdict": verdict, "openBlocking": []},
                )

    def test_positive_verdict_rejects_open_blocking_severities(self):
        for severity in ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM"):
            value = self.review()
            value["findings"] = [{"id": "block", "severity": severity, "status": " OPEN "}]
            with self.subTest(severity=severity), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "review-open-findings")

    def test_nonpositive_review_preserves_blocking_finding_ids(self):
        value = self.review()
        value["verdict"] = "CHANGES_REQUIRED"
        value["findings"] = [{"id": "needs-work", "severity": "MEDIUM", "status": "open"}]
        self.assertEqual(validate_independent_review(value)["openBlocking"], ["needs-work"])

    def test_exact_independence_flag_is_required(self):
        for reviewer in (None, {}, {"independent": False}, {"independent": 1}):
            value = self.review()
            value["reviewer"] = reviewer
            with self.subTest(reviewer=reviewer), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "review-not-independent")

    def test_unsupported_verdict_and_nonarray_findings_reject(self):
        for patch in ({"verdict": "RELEASE_READY"}, {"findings": None}, {"findings": {}}):
            value = self.review()
            value.update(patch)
            with self.subTest(patch=patch), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "invalid-review")

    def test_hidden_authority_control_rejects_before_verdict_filtering(self):
        for patch in (
            {"verdict": "ACCEP\u200bTED"},
            {"findings": [{"id": "hidden", "severity": "HI\u200bGH", "status": "open"}]},
        ):
            value = copy.deepcopy(self.review())
            value.update(patch)
            with self.subTest(patch=patch), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "authority-text-control")


class FocusedProvenanceCases(unittest.TestCase):
    """Known test-issuer facts only; no qualified native identity route."""

    def setUp(self):
        self.context = _context()
        self.proof = _attestation(self.context)

    def verify(self, *, proof=None, context=None):
        return verify_reviewer_attestation(
            self.proof if proof is None else proof,
            trusted_context=self.context if context is None else context,
        )

    @staticmethod
    def resigned(proof, domain=PREFIX):
        result = copy.deepcopy(proof)
        body = {key: value for key, value in result.items() if key != "signature"}
        result["signature"] = sign(SEED, domain + canonical_bytes(body)).hex()
        return result

    def test_valid_trusted_route(self):
        result = self.verify()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["guarantee"], "ATTESTED")
        self.assertEqual(result["subjectDigest"], self.context["expectedSubjectDigest"])

    def test_same_actor(self):
        self.assertEqual(self.verify(context={**self.context, "workerActorId": "reviewer"})["status"], "FAIL")

    def test_same_session(self):
        self.assertEqual(self.verify(context={**self.context, "workerSessionId": "reviewer-session"})["status"], "FAIL")

    def test_forged(self):
        proof = {**self.proof, "signature": "0" * 128}
        self.assertEqual(self.verify(proof=proof)["status"], "FAIL")

    def test_replayed(self):
        for field, digest in (("expectedAssignmentDigest", "c" * 64), ("expectedSubjectDigest", "d" * 64)):
            with self.subTest(field=field):
                self.assertEqual(self.verify(context={**self.context, field: digest})["status"], "FAIL")

    def test_untrusted_root(self):
        result = self.verify(context={**self.context, "expectedTrustRootDigest": "0" * 64})
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertEqual(result["guarantee"], "UNAVAILABLE")

    def test_actor_phase_allowlist(self):
        for field, value in (("actorIds", ["other-reviewer"]), ("phases", ["plan-review"])):
            context = copy.deepcopy(self.context)
            context["trustRoot"]["authorizedIssuers"][0][field] = value
            context["expectedTrustRootDigest"] = canonical_digest(context["trustRoot"])
            with self.subTest(field=field):
                self.assertEqual(self.verify(context=context)["status"], "UNSUPPORTED")

    def test_wrong_domain(self):
        self.assertEqual(self.verify(proof=self.resigned(self.proof, b"neutrality\x00"))["status"], "FAIL")

    def test_expiry(self):
        context = {**self.context, "referenceTime": "2026-09-23T02:04:01Z"}
        self.assertEqual(self.verify(context=context)["status"], "FAIL")

    def test_challenge(self):
        proof = copy.deepcopy(self.proof)
        proof["claims"]["nonce"] = "e" * 64
        self.assertEqual(self.verify(proof=self.resigned(proof))["status"], "FAIL")

    def test_idempotent_retry(self):
        context, proof = copy.deepcopy(self.context), copy.deepcopy(self.proof)
        first, second = self.verify(), self.verify()
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first, second)
        self.assertEqual(self.context, context)
        self.assertEqual(self.proof, proof)

    def test_native_context_unavailable(self):
        result = verify_reviewer_attestation(self.proof, trusted_context=None)
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertEqual(result["guarantee"], "UNAVAILABLE")
        supplied = {
            "reviewer": {"id": "reviewer", "independent": True},
            "reviewerProvenance": {"guarantee": "ATTESTED", "attestation": self.proof},
        }
        self.assertEqual(
            validate_native_reviewer_provenance(supplied, native_phase="task-review", trusted_context=self.context)[
                "status"
            ],
            "UNSUPPORTED",
        )

    def test_native_phase_map(self):
        for native, phase in (
            ("freeze", "plan-review"),
            ("task-review", "task-review"),
            ("implementation-audit", "task-review"),
            ("final-audit", "final-review"),
        ):
            context = copy.deepcopy(self.context)
            context["expectedPhase"] = phase
            context["trustRoot"]["authorizedIssuers"][0]["phases"] = [phase]
            context["expectedTrustRootDigest"] = canonical_digest(context["trustRoot"])
            proof = _attestation(context)
            review = {
                "reviewer": {"id": "reviewer", "independent": True},
                "reviewerProvenance": {"guarantee": "ATTESTED", "attestation": proof},
            }
            with self.subTest(native=native):
                self.assertEqual(
                    validate_native_reviewer_provenance(review, native_phase=native)["status"], "UNSUPPORTED"
                )
                proof["claims"]["phase"] = "task-review" if phase != "task-review" else "final-review"
                review["reviewerProvenance"]["attestation"] = self.resigned(proof)
                self.assertEqual(validate_native_reviewer_provenance(review, native_phase=native)["status"], "FAIL")

    def test_expected_attested_claim_stripped(self):
        for claim in (
            {"reviewerProvenance": {"guarantee": "ATTESTED", "attestation": None}},
            {"provenanceValidation": {"status": "PASS", "guarantee": "ATTESTED"}},
        ):
            review = {"reviewer": {"id": "reviewer", "independent": True}, **claim}
            with self.subTest(claim=claim):
                self.assertEqual(
                    validate_native_reviewer_provenance(review, native_phase="task-review")["status"], "FAIL"
                )


if __name__ == "__main__":
    unittest.main()


class BoundPlanReviewTests(unittest.TestCase):
    def test_impact_keeps_unrelated_requirement_out_and_reaches_final_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            selection = derive_delta_selection(case["baseline"]["subject"], case["delta"]["subject"])
        self.assertEqual(selection["mode"], "DELTA_ELIGIBLE")
        self.assertTrue(
            {"requirement:R1", "acceptance:A1", "workstream:W1", "path:src/one.py", "final:final"}
            <= set(selection["closure"])
        )
        self.assertNotIn("requirement:R2", selection["closure"])
        self.assertNotIn("workstream:W2", selection["closure"])

    def test_evidence_ownership_and_gate_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            graph = build_review_impact_graph(case["manifest"])
        closure = review_impact_closure([graph], ["evidence:E1"])
        self.assertTrue(
            {"acceptance:A1", "workstream:W1", "ownership:W1:src/one.py", "path:src/one.py", "final:final"}
            <= set(closure)
        )

    def test_complete_negative_baseline_can_be_closed_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            result = self.validate(case)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["fullReview"])
        self.assertEqual(case["baseline"]["verdict"], "CHANGES_REQUIRED")
        self.assertFalse(case["delta"]["fullReview"])

    def test_accepted_baseline_also_preserves_complete_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.validate(synthetic_case(Path(tmp), negative=False))["status"], "PASS")

    def test_missing_closure_and_applicability_refuse(self):
        for key in ("findingClosures", "currentApplicability"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                case = synthetic_case(Path(tmp))
                case["delta"].pop(key)
                with self.assertRaises(LifecycleError):
                    self.validate(case)

    def test_forged_closure_or_full_flag_cannot_reduce_coverage(self):
        for key, value in (("coveredNodes", []), ("graphDigest", "0" * 64), ("selectionDigest", "0" * 64)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                case = synthetic_case(Path(tmp))
                case["delta"]["reviewScope"][key] = value
                with self.assertRaises(LifecycleError):
                    self.validate(case)
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            case["delta"]["fullReview"] = True
            with self.assertRaises(LifecycleError):
                validate_bound_plan_review(case["delta"])

    def test_runtime_and_security_changes_force_full_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
        before = case["baseline"]["subject"]
        for field in ("runtime", "security", "unknown"):
            after = copy.deepcopy(case["delta"]["subject"])
            if field == "runtime":
                after["runtimeInputs"]["runtime.py"] = "f" * 64
            elif field == "security":
                after["manifest"]["securityGates"] = ["changed"]
            else:
                after["manifest"]["unparsedAuthority"] = True
            with self.subTest(field=field):
                self.assertEqual(derive_delta_selection(before, after)["mode"], "FULL_REQUIRED")

    def test_call_outside_original_authority_is_not_rehabilitated(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            case["baseline"]["reviewAuthority"]["expiresAt"] = "2026-09-30T00:00:00Z"
            with self.assertRaises(LifecycleError) as raised:
                self.validate(case)
            self.assertEqual(raised.exception.code, "review-authority-expired")

    def test_coordinator_and_unknown_finding_states_refuse(self):
        for change in ("role", "finding"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                case = synthetic_case(Path(tmp))
                if change == "role":
                    case["delta"]["reviewer"]["role"] = "coordinator"
                else:
                    case["baseline"]["findings"][0]["status"] = "UNKNOWN"
                with self.assertRaises(LifecycleError):
                    self.validate(case)

    def test_report_byte_caps_apply_before_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            case["sizes"]["plans/r1/review.json"] = 8 * 1024 * 1024
            with self.assertRaises(LifecycleError) as raised:
                self.validate(case)
            self.assertEqual(raised.exception.code, "review-chain-limit")

    def test_duplicate_delivery_does_not_create_a_voice_or_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            seat = case["manifest"]["extensions"]["reviewPolicy"]["requiredSeats"][0]
            # Duplicate transport is allowed only under declared selectors.
            case["reports"]["delivery.json"] = copy.deepcopy(case["baseline"])
            case["sizes"]["delivery.json"] = case["sizes"][seat["baseline"]]
            seat["reports"].append("delivery.json")
            refresh_candidate(Path(tmp), case)
            result = self.validate(case)
            self.assertEqual(result["seats"][0]["reportCount"], 2)
            self.assertEqual(result["seats"][0]["dependencyEdges"], 1)

    def test_duplicate_required_seats_cannot_reuse_one_independent_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp), duplicate_seat=True)
            with self.assertRaises(LifecycleError) as raised:
                self.validate(case)
            self.assertEqual(raised.exception.code, "review-duplicate-seat")

    def test_longest_chain_eight_edges_accepts_nine_refuses(self):
        for edges in (8, 9):
            with self.subTest(edges=edges), tempfile.TemporaryDirectory() as tmp:
                case = synthetic_chain(Path(tmp), edges)
                if edges == 8:
                    self.assertEqual(self.validate(case)["seats"][0]["dependencyEdges"], 8)
                else:
                    with self.assertRaises(LifecycleError) as raised:
                        self.validate(case)
                    self.assertEqual(raised.exception.code, "review-chain-limit")

    def test_stricter_governing_limits_and_missing_parent_refuse(self):
        for limit in ("reports", "dependencyEdges", "reportBytes", "missingParent"):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as tmp:
                limits = None if limit == "missingParent" else {limit: 1}
                case = synthetic_chain(Path(tmp), 3, policy_limits=limits)
                if limit == "missingParent":
                    case["delta"]["dependsOn"] = ["0" * 64]
                with self.assertRaises(LifecycleError):
                    self.validate(case)

    @staticmethod
    def validate(case):
        return validate_review_composition(
            case["manifest"], case["composite"], case["reports"], report_sizes=case["sizes"]
        )
