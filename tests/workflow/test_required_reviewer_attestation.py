"""Strict reviewer native finalization under synthetic selected public trust."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.reviewer_identity_schemas import REVIEWER_REQUIRED_STATE, reviewer_attestation_authority
from agent_lifecycle.workflow.finalization import apply_final_audit_outcome, finalize_run
from agent_lifecycle.workflow.implementation_audit_gate import validate_task_implementation_audit_artifact
from agent_lifecycle.workflow.reviewer_gate import reviewer_decision_lineage
from agent_lifecycle.workflow.reviews import validate_task_review
from tests.contracts.test_operator_signature import envelope, inventory, state
from tests.review.test_reviewer_attestation_strict import OBSERVED, REVIEWER, WORKER, attest, policy_for
from tests.workflow.helpers import _final_audit
from tests.workflow.test_operator_signature_gates import write


class StrictNativeReviewerTests(TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(strict=True)
        self.state_path = self.root / "run.state.json"
        self.audit = "final-audit.json"
        self.value = state(phase="FINAL_AUDIT")
        policy = policy_for("final-audit", "final-implementation-audit")
        marker = reviewer_attestation_authority(policy)
        manifest = {
            "author": {"id": WORKER[0], "runId": WORKER[1]},
            "reviewerAttestationAuthority": marker,
            "reviewerAttestationPolicy": policy,
        }
        self.value.update(
            schemaVersion=REVIEWER_REQUIRED_STATE,
            reviewerAttestationPolicy=policy,
            reviewerAttestationAuthority=marker,
            manifestPath="plan.manifest.json",
            planDigest=canonical_digest(manifest),
            authorization={"required": False, "granted": True},
        )
        write(self.root / "plan.manifest.json", manifest)
        write(self.state_path, self.value)
        self.report = _final_audit()
        self.report.update(
            runId=self.value["runId"],
            packageId=self.value["packageId"],
            sourceRevision=self.value["sourceRevision"],
            planDigest=self.value["planDigest"],
            verdict="ACCEPTED",
            taskIds=[],
            findingIds=[],
            auditor=REVIEWER,
        )
        self.report["completionSignal"]["planDigest"] = self.value["planDigest"]
        self.report = attest(
            policy, self.report, phase="final-audit", lineage=reviewer_decision_lineage(self.value),
        )
        write(self.root / self.audit, self.report)

    def apply(self, verdict="ACCEPTED"):
        with patch("agent_lifecycle.workflow.reviewer_gate.reviewer_observed_at", return_value=OBSERVED):
            return apply_final_audit_outcome(
                self.state_path, operation_id="accept-review", expected_revision=1,
                source_revision="source", final_audit_path=self.audit, verdict=verdict,
                reason="Synthetic strict reviewer test",
            )

    def finalize(self, typed_report=None):
        with patch("agent_lifecycle.workflow.reviewer_gate.reviewer_observed_at", return_value=OBSERVED):
            return finalize_run(
                self.state_path, operation_id="finish", expected_revision=2, source_revision="source",
                final_audit_path=self.audit, proof_path="proof.json", reason="Synthetic strict reviewer test",
                final_implementation_audit_path=typed_report,
            )

    def test_actual_outcome_and_finalize_bind_same_signed_report_and_operator_key(self):
        self.apply()
        current = read_json_object(self.state_path)
        admission = current["finalAuditOutcome"]["finalAudit"]["reviewerAdmission"]
        self.assertEqual(admission["observedAt"], OBSERVED)
        signature = envelope(current, "accept", operation_id="finish", subject=self.report)
        write(self.root / (self.audit + ".operator-signature.json"), signature)
        typed = {
            **{key: current[key] for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")},
            "schemaVersion": "agent-final-implementation-audit.v1",
            "status": "PASS", "findings": [], "blockers": [], "auditor": REVIEWER,
            "productionPromotionClaimed": False,
        }
        signed_typed = attest(
            current["reviewerAttestationPolicy"], typed, phase="final-implementation-audit",
            lineage=reviewer_decision_lineage(current),
        )
        signed_typed["auditDigest"] = canonical_digest(signed_typed)
        write(self.root / "typed.json", typed)
        before = inventory(self.root)
        with self.assertRaisesRegex(LifecycleError, "requires an exact signed review"):
            self.finalize("typed.json")
        self.assertEqual(inventory(self.root), before)
        write(self.root / "typed.json", signed_typed)
        self.assertEqual(self.finalize("typed.json")["phase"], "COMPLETE")
        actual = read_json_object(self.state_path)
        self.assertEqual(actual["schemaVersion"], REVIEWER_REQUIRED_STATE)
        proof = read_json_object(self.root / "proof.json")
        self.assertTrue(proof["operatorSignature"]["signatureVerified"])
        self.assertEqual(proof["finalAudit"]["reviewerAdmission"], admission)
        self.assertEqual(proof["finalImplementationAudit"]["audit"]["reviewerAdmission"]["phase"],
                         "final-implementation-audit")

    def test_wrong_outcome_scope_and_missing_review_signature_do_not_write(self):
        before = inventory(self.root)
        with self.assertRaisesRegex(LifecycleError, "must bind its exact outcome scope"):
            self.apply("BLOCKED")
        self.assertEqual(inventory(self.root), before)

        report = {k: v for k, v in self.report.items() if k != "reviewerProvenance"}
        write(self.root / self.audit, report)
        before = inventory(self.root)
        with self.assertRaisesRegex(LifecycleError, "requires an exact signed review"):
            self.apply()
        self.assertEqual(inventory(self.root), before)

    def test_finalization_refuses_substitution_after_exact_outcome_without_writes(self):
        self.apply()
        write(self.root / self.audit, {**self.report, "description": "different signed content"})
        before = inventory(self.root)
        with self.assertRaisesRegex(LifecycleError, "differs from the exact admitted outcome"):
            self.finalize()
        self.assertEqual(inventory(self.root), before)


class StrictTaskReviewerTests(TestCase):
    def test_native_review_gate_checks_attestation_in_addition_to_existing_lineage(self):
        policy = policy_for("task-review:WS-01")
        value = state()
        value.update(
            schemaVersion=REVIEWER_REQUIRED_STATE,
            reviewerAttestationPolicy=policy,
            reviewerAttestationAuthority=reviewer_attestation_authority(policy),
        )
        result = {"actor": WORKER[0], "actorRunId": WORKER[1], "summary": "test result"}
        task = {
            "id": "WS-01", "attempt": 1, "packet": {"sha256": "9" * 64},
            "result": {"sha256": canonical_digest(result)},
        }
        unsigned = {
            "schemaVersion": "agent-task-review.v2", "runId": value["runId"], "taskId": task["id"],
            "attempt": 1, "planDigest": value["planDigest"], "resultHash": task["result"]["sha256"],
            "taskPacketHash": task["packet"]["sha256"], "reviewId": "task-review-1", "reviewer": REVIEWER,
            "verdict": "ACCEPTED", "findings": [],
        }
        signed = attest(policy, unsigned, phase="task-review", lineage=reviewer_decision_lineage(value, task))
        with patch("agent_lifecycle.workflow.reviewer_gate.reviewer_observed_at", return_value=OBSERVED):
            admission = validate_task_review(value, task, signed, result=result)
            self.assertEqual(admission["reportDigest"], canonical_digest(signed))
            with self.assertRaisesRegex(LifecycleError, "requires an exact signed review"):
                validate_task_review(value, task, unsigned, result=result)
            with self.assertRaisesRegex(LifecycleError, "did not verify"):
                validate_task_review(value, {**task, "attempt": 2}, signed, result=result)

    def test_typed_task_gate_pins_admission_and_revalidates_at_archived_time(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve(strict=True)
        policy = policy_for("implementation-audit:WS-01")
        value = state(phase="RUNNING")
        manifest = {"status": "FROZEN"}
        value.update(
            schemaVersion=REVIEWER_REQUIRED_STATE,
            reviewerAttestationPolicy=policy,
            reviewerAttestationAuthority=reviewer_attestation_authority(policy),
            manifestPath="plan.manifest.json",
            planDigest=canonical_digest(manifest),
        )
        write(root / "plan.manifest.json", manifest)
        result = {"actor": WORKER[0], "actorRunId": WORKER[1]}
        write(root / "result.json", result)
        task = {
            "id": "WS-01",
            "attempt": 1,
            "status": "VERIFYING",
            "packet": {"sha256": "9" * 64},
            "result": {
                "path": "result.json", "sha256": canonical_digest(result), "bytes": (root / "result.json").stat().st_size,
            },
        }
        report = {
            **{key: value[key] for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")},
            "schemaVersion": "agent-implementation-audit-report.v1",
            "taskId": "WS-01", "attempt": 1, "status": "PASS", "verdict": "ACCEPTED", "auditor": REVIEWER,
            "findings": [], "blockers": [], "productionPromotionClaimed": False,
        }
        signed = attest(
            policy, report, phase="implementation-audit", lineage=reviewer_decision_lineage(value, task),
        )
        signed["reportDigest"] = canonical_digest(signed)
        write(root / "typed.json", signed)
        with patch("agent_lifecycle.workflow.reviewer_gate.reviewer_observed_at", return_value=OBSERVED):
            admitted = validate_task_implementation_audit_artifact(root / "state.json", value, task, "typed.json")
        accepted = {**task, "status": "ACCEPTED", "implementationAuditReport": admitted}
        restored = validate_task_implementation_audit_artifact(root / "state.json", value, accepted, "typed.json")
        self.assertEqual(admitted, restored)
        write(root / "typed.json", {**signed, "verdict": "REWORK"})
        with self.assertRaisesRegex(LifecycleError, "did not verify"):
            validate_task_implementation_audit_artifact(root / "state.json", value, accepted, "typed.json")
