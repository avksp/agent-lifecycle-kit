from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.external_job_schemas import (
    build_external_job_request,
    build_external_job_result,
    build_external_job_status,
)
from agent_lifecycle.contracts.review_round_schemas import (
    build_finding_disposition,
    build_review_round_participation,
)
from agent_lifecycle.review_mesh import (
    build_review_mesh_assignment,
    build_review_mesh_profile,
    build_review_mesh_result,
    synthesize_review_mesh_results,
)
from agent_lifecycle.review_mesh.synthesis import evaluate_review_round


class ReviewMeshSynthesisTests(unittest.TestCase):
    def test_synthesis_accepts_matching_findings_from_multiple_reviewers(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        first = _result(profile, "RM-1", "reviewer-a", [{"id": "F1", "severity": "LOW", "status": "open"}])
        second = _result(profile, "RM-2", "reviewer-b", [{"id": "F1", "severity": "LOW", "status": "open"}])

        synthesis = synthesize_review_mesh_results(profile=profile, results=[first, second])

        self.assertEqual(synthesis["status"], "PASS")
        self.assertEqual([item["findingKey"] for item in synthesis["agreement"]], ["F1"])
        self.assertEqual([item["id"] for item in synthesis["acceptedFindings"]], ["F1"])
        self.assertEqual(synthesis["unresolvedFindings"], [])

    def test_synthesis_keeps_conflicting_finding_unresolved(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        first = _result(profile, "RM-1", "reviewer-a", [{"id": "F1", "severity": "LOW", "status": "open"}])
        second = _result(profile, "RM-2", "reviewer-b", [{"id": "F1", "severity": "HIGH", "status": "open"}])

        synthesis = synthesize_review_mesh_results(profile=profile, results=[first, second])

        self.assertEqual(synthesis["status"], "INCONCLUSIVE")
        self.assertEqual([item["findingKey"] for item in synthesis["conflicts"]], ["F1"])
        self.assertEqual([item["id"] for item in synthesis["unresolvedFindings"]], ["F1"])

    def test_explicit_rejection_overrides_repeated_finding(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        first = _result(profile, "RM-1", "reviewer-a", [{"id": "F1", "severity": "LOW", "status": "open"}])
        second = _result(profile, "RM-2", "reviewer-b", [{"id": "F1", "severity": "LOW", "status": "open"}])

        synthesis = synthesize_review_mesh_results(
            profile=profile, results=[first, second], rejected_finding_ids=["F1"]
        )

        self.assertEqual(synthesis["status"], "PASS")
        self.assertEqual([item["id"] for item in synthesis["rejectedFindings"]], ["F1"])
        self.assertEqual(synthesis["acceptedFindings"], [])

    def test_agreed_open_blocking_finding_needs_immutable_rejection(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        finding = {"id": "F1", "severity": "HIGH", "status": "open"}
        first = _result(profile, "RM-1", "reviewer-a", [finding])
        second = _result(profile, "RM-2", "reviewer-b", [finding])
        synthesis = synthesize_review_mesh_results(profile=profile, results=[first, second])
        participation = _participation(findings=[finding], overall="REWORK", job_verdict="FAIL")
        confirmed = build_finding_disposition(
            finding=synthesis["acceptedFindings"][0],
            disposition="CONFIRMED",
            reason_code="reproduced",
            evidence_digests=["a" * 64],
            operation_id="confirm-f1",
        )

        continuing = evaluate_review_round(
            synthesis=synthesis,
            participations=[participation],
            dispositions=[confirmed],
            round_number=1,
            max_rounds=2,
        )
        exhausted = evaluate_review_round(
            synthesis=synthesis,
            participations=[participation],
            dispositions=[confirmed],
            round_number=2,
            max_rounds=2,
            exhaustion_outcome="REPLAN_REQUIRED",
        )
        rejected = build_finding_disposition(
            finding=synthesis["acceptedFindings"][0],
            disposition="REJECTED",
            reason_code="false-positive",
            evidence_digests=["b" * 64],
            operation_id="reject-f1",
        )
        accepted = evaluate_review_round(
            synthesis=synthesis,
            participations=[participation],
            dispositions=[rejected],
            round_number=1,
            max_rounds=2,
        )

        self.assertEqual(continuing["outcome"], "CONTINUE")
        self.assertEqual(exhausted["outcome"], "REPLAN_REQUIRED")
        self.assertEqual(accepted["outcome"], "ACCEPTED")

    def test_findings_only_import_has_no_participation_effect(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        synthesis = synthesize_review_mesh_results(
            profile=profile,
            results=[_result(profile, "RM-1", "reviewer-a", [])],
        )
        evaluation = evaluate_review_round(
            synthesis=synthesis,
            participations=[],
            dispositions=[],
            round_number=1,
            max_rounds=2,
        )
        self.assertEqual(evaluation["outcome"], "CONTINUE")
        self.assertIn("review-round-no-participating-reviewer", {item["code"] for item in evaluation["blockers"]})

    def test_clean_participating_round_stops_as_accepted(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        synthesis = synthesize_review_mesh_results(
            profile=profile,
            results=[_result(profile, "RM-1", "reviewer-a", [])],
        )
        evaluation = evaluate_review_round(
            synthesis=synthesis,
            participations=[_participation(findings=[], overall="ACCEPTED", job_verdict="PASS")],
            dispositions=[],
            round_number=1,
            max_rounds=4,
        )
        self.assertEqual(evaluation["outcome"], "ACCEPTED")

    def test_participating_finding_omitted_from_synthesis_fails_closed(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        synthesis = synthesize_review_mesh_results(
            profile=profile,
            results=[_result(profile, "RM-1", "reviewer-a", [])],
        )
        finding = {"id": "F-HIDDEN", "severity": "HIGH", "status": "open"}

        evaluation = evaluate_review_round(
            synthesis=synthesis,
            participations=[_participation(findings=[finding], overall="REWORK", job_verdict="FAIL")],
            dispositions=[],
            round_number=1,
            max_rounds=2,
        )

        self.assertEqual(evaluation["outcome"], "CONTINUE")
        self.assertEqual(evaluation["findingIds"], ["F-HIDDEN"])
        self.assertEqual(evaluation["openBlockingFindingIds"], ["F-HIDDEN"])
        self.assertIn(
            "review-round-participation-finding-unjoined",
            {item["code"] for item in evaluation["blockers"]},
        )

    def test_each_blocking_severity_blocks_single_reviewer_round(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        for severity in ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM"):
            with self.subTest(severity=severity):
                finding = {"id": f"F-{severity}", "severity": severity, "status": "open"}
                synthesis = synthesize_review_mesh_results(
                    profile=profile,
                    results=[_result(profile, "RM-1", "reviewer-a", [finding])],
                )
                disposition = build_finding_disposition(
                    finding=synthesis["unresolvedFindings"][0],
                    disposition="CONFIRMED",
                    reason_code="reproduced",
                    evidence_digests=["a" * 64],
                    operation_id=f"confirm-{severity.lower()}",
                )
                evaluation = evaluate_review_round(
                    synthesis=synthesis,
                    participations=[_participation(findings=[finding], overall="REWORK", job_verdict="FAIL")],
                    dispositions=[disposition],
                    round_number=1,
                    max_rounds=2,
                )
                self.assertEqual(evaluation["outcome"], "CONTINUE")
                self.assertEqual(evaluation["openBlockingFindingIds"], [f"F-{severity}"])
                exhausted = evaluate_review_round(
                    synthesis=synthesis,
                    participations=[_participation(findings=[finding], overall="REWORK", job_verdict="FAIL")],
                    dispositions=[disposition],
                    round_number=2,
                    max_rounds=2,
                    exhaustion_outcome="OPERATOR_DECISION",
                )
                self.assertEqual(exhausted["outcome"], "OPERATOR_DECISION")

    def test_agreement_never_closes_each_blocking_severity(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        for severity in ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM"):
            with self.subTest(severity=severity):
                finding = {"id": f"F-{severity}", "severity": severity, "status": "open"}
                synthesis = synthesize_review_mesh_results(
                    profile=profile,
                    results=[
                        _result(profile, "RM-1", "reviewer-a", [finding]),
                        _result(profile, "RM-2", "reviewer-b", [finding]),
                    ],
                )
                confirmed = build_finding_disposition(
                    finding=synthesis["acceptedFindings"][0],
                    disposition="CONFIRMED",
                    reason_code="reproduced",
                    evidence_digests=["c" * 64],
                    operation_id=f"confirm-agreed-{severity.lower()}",
                )
                evaluation = evaluate_review_round(
                    synthesis=synthesis,
                    participations=[_participation(findings=[finding], overall="REWORK", job_verdict="FAIL")],
                    dispositions=[confirmed],
                    round_number=1,
                    max_rounds=2,
                )
                self.assertEqual(evaluation["outcome"], "CONTINUE")
                self.assertEqual(evaluation["openBlockingFindingIds"], [f"F-{severity}"])

    def test_participation_deletion_duplication_and_exhaustion_fail_closed(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        synthesis = synthesize_review_mesh_results(
            profile=profile,
            results=[_result(profile, "RM-1", "reviewer-a", [])],
        )
        participation = _participation(findings=[], overall="ACCEPTED", job_verdict="PASS")

        deleted = evaluate_review_round(
            synthesis=synthesis,
            participations=[],
            dispositions=[],
            round_number=2,
            max_rounds=2,
        )
        duplicated = evaluate_review_round(
            synthesis=synthesis,
            participations=[participation, participation],
            dispositions=[],
            round_number=1,
            max_rounds=2,
        )

        self.assertEqual(deleted["outcome"], "BLOCKED")
        self.assertEqual(deleted["openBlockingFindingIds"], [])
        self.assertIn("review-round-no-participating-reviewer", {item["code"] for item in deleted["blockers"]})
        self.assertEqual(duplicated["outcome"], "CONTINUE")
        self.assertIn("review-round-participation-duplicate", {item["code"] for item in duplicated["blockers"]})

    def test_missing_orphan_and_lineage_mismatched_dispositions_fail_closed(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        finding = {"id": "F1", "severity": "LOW", "status": "open"}
        synthesis = synthesize_review_mesh_results(
            profile=profile,
            results=[_result(profile, "RM-1", "reviewer-a", [finding])],
            accepted_finding_ids=["F1"],
        )
        participation = _participation(findings=[finding], overall="ACCEPTED", job_verdict="PASS")
        orphan_finding = {"id": "F2", "severity": "LOW", "status": "open"}
        orphan = build_finding_disposition(
            finding=orphan_finding,
            disposition="CONFIRMED",
            reason_code="reproduced",
            evidence_digests=["a" * 64],
            operation_id="confirm-f2",
        )
        mismatched = build_finding_disposition(
            finding={**finding, "message": "different lineage"},
            disposition="CONFIRMED",
            reason_code="reproduced",
            evidence_digests=["b" * 64],
            operation_id="confirm-f1",
        )

        missing_evaluation = evaluate_review_round(
            synthesis=synthesis,
            participations=[participation],
            dispositions=[],
            round_number=1,
            max_rounds=2,
        )
        orphan_evaluation = evaluate_review_round(
            synthesis=synthesis,
            participations=[participation],
            dispositions=[orphan],
            round_number=1,
            max_rounds=2,
        )
        mismatch_evaluation = evaluate_review_round(
            synthesis=synthesis,
            participations=[participation],
            dispositions=[mismatched],
            round_number=1,
            max_rounds=2,
        )

        self.assertIn("review-round-disposition-missing", {item["code"] for item in missing_evaluation["blockers"]})
        self.assertIn("review-round-disposition-orphan", {item["code"] for item in orphan_evaluation["blockers"]})
        self.assertIn(
            "review-round-disposition-lineage-mismatch",
            {item["code"] for item in mismatch_evaluation["blockers"]},
        )


def _result(profile: dict, assignment_id: str, reviewer_id: str, findings: list[dict]) -> dict:
    assignment = build_review_mesh_assignment(
        profile=profile,
        assignment_id=assignment_id,
        subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
        reviewer={"id": reviewer_id, "role": "reviewer", "modelClass": "strong-reasoning"},
        blocking=True,
    )
    return build_review_mesh_result(
        profile=profile,
        assignment=assignment,
        budget_usage={"invocations": 1, "inputTokens": 100, "outputTokens": 20, "wallSeconds": 3},
        findings=findings,
    )


def _participation(*, findings: list[dict], overall: str, job_verdict: str) -> dict:
    accepted = overall == "ACCEPTED"
    verdict = {
        "schemaVersion": "agent-review-verdict.v1",
        "overall": overall,
        "dimensions": {
            "requirementFit": {"status": "PASS", "reasonCode": "fit", "summary": "Requirements checked."},
            "implementationQuality": {
                "status": "PASS" if accepted else "FAIL",
                "reasonCode": "quality",
                "summary": "Implementation checked.",
            },
            "evidenceQuality": {"status": "PASS", "reasonCode": "evidence", "summary": "Evidence checked."},
            "residualRisk": {"status": "PASS", "reasonCode": "risk", "summary": "Risk checked."},
        },
        "routing": {"nextAction": "accept" if accepted else "fix-implementation", "target": "task"},
    }
    request = build_external_job_request(
        job_id="round-review",
        attempt=1,
        parent_job_id=None,
        parent_attempt=None,
        parent_request_digest=None,
        adapter_id="synthetic",
        operation="review",
        execution_kind="PROCESS",
        descriptor_digest="1" * 64,
        plan_digest="2" * 64,
        plan_lock_digest="3" * 64,
        source_revision="0123456789abcdef",
        source_snapshot_digest="4" * 64,
        limits={
            "maxWallSeconds": 60,
            "maxAttempts": 3,
            "maxOutputBytes": 1024,
            "maxArtifactBytes": 1024,
            "maxArtifacts": 4,
            "maxCostMicros": 1_000_000,
            "maxReportedTokens": 10_000,
            "cancelGraceSeconds": 2,
        },
    )
    status = build_external_job_status(
        request=request,
        state="SUCCEEDED",
        sequence=2,
        observed_at="2026-08-26T03:30:02Z",
        started_at="2026-08-26T03:30:00Z",
        ended_at="2026-08-26T03:30:02Z",
        process_cleanup_status="PASS",
        usage={"wallMilliseconds": 2000, "outputBytes": 0, "artifactBytes": 0},
    )
    result = build_external_job_result(
        result_id="round-result",
        request=request,
        status=status,
        verdict=job_verdict,
        complete=True,
        artifacts=[],
        output_digest=canonical_digest(verdict),
        output_bytes=len(canonical_bytes(verdict)),
    )
    return build_review_round_participation(
        reviewer_id="reviewer-a",
        review_verdict=verdict,
        findings=findings,
        job_request=request,
        job_status=status,
        job_result=result,
    )


if __name__ == "__main__":
    unittest.main()
