from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import (
    build_security_analysis_audit,
    build_security_verification_assignment,
    validate_security_analysis_audit,
    validate_security_verification_assignment,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.review_mesh import build_security_verification_assignment_packet
from agent_lifecycle.workflow import accept_task, commit_task_result, start_task
from agent_lifecycle.workflow.implementation_audit_gate import _security_assignment_payload
from tests.workflow.test_task_acceptance_audit_gate import _write_bundle, _write_result_review


class SecurityAnalysisWorkflowTests(unittest.TestCase):
    def test_adopted_task_carries_security_policy(self) -> None:
        from agent_lifecycle.workflow.plan_adoption import _build_tasks

        manifest = {
            "package": {"artifactRoot": "tasks/package"},
            "extensions": {
                "securityAnalysis": {
                    "profileId": "security-analysis.v1",
                    "activation": "read-only-by-default",
                    "implementationAudit": {
                        "required": True,
                        "minimumSeverity": "high",
                        "independentVerificationRequired": True,
                        "enforcedAt": "task-acceptance",
                        "propagation": "manifest-to-adopted-task",
                    },
                }
            },
            "workstreams": [{"id": "WS-01", "owner": "worker", "writes": [], "dependsOn": []}],
        }
        task = _build_tasks(manifest, {})[0]
        self.assertEqual(task["securityAnalysis"]["profileId"], "security-analysis.v1")
        self.assertEqual(task["implementationAudit"]["minimumSeverity"], "high")

    def test_high_severity_cannot_accept_from_implementer_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=False)
            state = json.loads(Path(bundle["statePath"]).read_text(encoding="utf-8"))
            state["tasks"][0]["securityAnalysis"] = {
                "enabled": True,
                "severity": "HIGH",
                "implementationAudit": {"required": True, "independentVerificationRequired": True},
            }
            state["tasks"][0]["owner"] = "implementer"
            Path(bundle["statePath"]).write_text(json.dumps(state), encoding="utf-8")
            start_task(bundle["statePath"], task_id="WS-01", operation_id="start", expected_revision=1, source_revision="source", reason="test")
            result_path, review_path = _write_result_review(root, bundle)
            commit_task_result(bundle["statePath"], task_id="WS-01", operation_id="result", expected_revision=2, source_revision="source", result_path=result_path, reason="test")
            with self.assertRaises(LifecycleError) as caught:
                accept_task(bundle["statePath"], task_id="WS-01", operation_id="accept", expected_revision=3, review_path=review_path, reason="test")
            self.assertEqual(caught.exception.code, "security-analysis-verification-required")

    def test_matching_independent_assignment_accepts_high_severity_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=False)
            state = json.loads(Path(bundle["statePath"]).read_text(encoding="utf-8"))
            state["tasks"][0]["securityAnalysis"] = {
                "enabled": True,
                "severity": "HIGH",
                "implementationAudit": {"required": True, "independentVerificationRequired": True},
                "verificationEvidence": {
                    "independentEvidenceIds": ["EV93-REVIEW"],
                    "assignmentPath": "work/review/assignment.json",
                },
            }
            state["tasks"][0]["owner"] = "implementer"
            Path(bundle["statePath"]).write_text(json.dumps(state), encoding="utf-8")
            start_task(bundle["statePath"], task_id="WS-01", operation_id="start", expected_revision=1, source_revision="source", reason="test")
            result_path, review_path = _write_result_review(root, bundle)
            commit_task_result(bundle["statePath"], task_id="WS-01", operation_id="result", expected_revision=2, source_revision="source", result_path=result_path, reason="test")
            assignment = build_security_verification_assignment_packet(
                source={
                    "kind": "TASK",
                    "label": "WS-01",
                    "digest": "a" * 64,
                    "sourceRevision": "source",
                    "sourceLineageDigest": "b" * 64,
                    "primaryProducerClass": "implementer",
                    "primaryImplementationDigest": "c" * 64,
                },
                assignment_id="assignment-1",
                reviewer_id="security-reviewer",
                evidence_ids=["EV93-REVIEW"],
            )
            write_json_create(root / "work/review/assignment.json", assignment)
            audit = build_security_analysis_audit(
                run_id="run",
                task_id="WS-01",
                attempt=1,
                plan_digest=bundle["planDigest"],
                source_revision="source",
                auditor={"id": "security-reviewer", "independent": True, "producerClass": "independent-reviewer"},
                verdict="ACCEPTED",
                independent_evidence_ids=["EV93-REVIEW"],
            )
            audit_path = "work/review/implementation-audit.json"
            write_json_create(root / audit_path, audit)
            payload = accept_task(bundle["statePath"], task_id="WS-01", operation_id="accept", expected_revision=3, review_path=review_path, implementation_audit_path=audit_path, reason="verified")
            self.assertEqual(payload["tasks"][0]["status"], "ACCEPTED")

    def test_security_audit_rejects_implementer_producer_after_digest_recalculation(self) -> None:
        audit = build_security_analysis_audit(
            run_id="run",
            task_id="WS-01",
            attempt=1,
            plan_digest="a" * 64,
            source_revision="source",
            auditor={"id": "implementer", "independent": True, "producerClass": "implementer"},
            verdict="ACCEPTED",
            independent_evidence_ids=["EV93-REVIEW"],
        )
        validation = validate_security_analysis_audit(audit)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "security-analysis-verification-not-independent",
            {item["code"] for item in validation["blockers"]},
        )

    def test_failed_verification_assignment_cannot_authorize_acceptance(self) -> None:
        assignment = build_security_verification_assignment(
            assignment_id="assignment-1",
            run_id="run",
            task_id="WS-01",
            attempt=1,
            plan_digest="a" * 64,
            source_revision="source",
            reviewer={"id": "security-reviewer", "independent": True, "producerClass": "independent-reviewer"},
            independent_evidence_ids=["EV93-REVIEW"],
        )
        assignment["status"] = "FAIL"
        assignment["assignmentDigest"] = canonical_digest(
            {key: value for key, value in assignment.items() if key != "assignmentDigest"}
        )
        validation = validate_security_verification_assignment(assignment)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "security-analysis-verification-assignment-status-invalid",
            {item["code"] for item in validation["blockers"]},
        )

    def test_security_assignment_payload_rejects_advisory_packet_after_digest_recalculation(self) -> None:
        packet = build_security_verification_assignment_packet(
            source={
                "kind": "TASK",
                "label": "WS-01",
                "digest": "a" * 64,
                "sourceRevision": "source",
                "sourceLineageDigest": "b" * 64,
                "primaryProducerClass": "implementer",
                "primaryImplementationDigest": "c" * 64,
            },
            assignment_id="assignment-1",
            reviewer_id="security-reviewer",
            evidence_ids=["EV93-REVIEW"],
        )
        packet["assignment"]["independenceRequirement"] = None
        packet["assignment"]["assignmentDigest"] = canonical_digest(
            {key: value for key, value in packet["assignment"].items() if key != "assignmentDigest"}
        )
        packet["packetDigest"] = canonical_digest(
            {key: value for key, value in packet.items() if key != "packetDigest"}
        )
        with self.assertRaises(LifecycleError) as raised:
            _security_assignment_payload(
                packet,
                state={"runId": "run", "planDigest": "a" * 64, "sourceRevision": "source"},
                task={"id": "WS-01", "attempt": 1},
            )
        self.assertEqual(raised.exception.code, "security-analysis-verification-required")

    def test_security_assignment_payload_rejects_missing_source_revision_after_digest_recalculation(self) -> None:
        packet = build_security_verification_assignment_packet(
            source={
                "kind": "TASK",
                "label": "WS-01",
                "digest": "a" * 64,
                "sourceRevision": "source",
                "sourceLineageDigest": "b" * 64,
                "primaryProducerClass": "implementer",
                "primaryImplementationDigest": "c" * 64,
            },
            assignment_id="assignment-1",
            reviewer_id="security-reviewer",
            evidence_ids=["EV93-REVIEW"],
        )
        del packet["assignment"]["subject"]["sourceRevision"]
        packet["assignment"]["assignmentDigest"] = canonical_digest(
            {key: value for key, value in packet["assignment"].items() if key != "assignmentDigest"}
        )
        packet["packetDigest"] = canonical_digest(
            {key: value for key, value in packet.items() if key != "packetDigest"}
        )
        with self.assertRaises(LifecycleError) as raised:
            _security_assignment_payload(
                packet,
                state={"runId": "run", "planDigest": "a" * 64, "sourceRevision": "source"},
                task={"id": "WS-01", "attempt": 1},
            )
        self.assertEqual(raised.exception.code, "security-analysis-verification-required")


if __name__ == "__main__":
    unittest.main()
