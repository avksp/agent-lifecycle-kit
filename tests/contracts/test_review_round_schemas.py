from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.external_job_schemas import (
    build_external_job_request,
    build_external_job_result,
    build_external_job_status,
)
from agent_lifecycle.contracts.review_round_schemas import (
    build_finding_disposition,
    build_review_round_evaluation,
    build_review_round_participation,
    merge_finding_dispositions,
    validate_finding_disposition,
    validate_review_round_evaluation,
    validate_review_round_participation,
)


class ReviewRoundSchemaTests(unittest.TestCase):
    def test_succeeded_pass_and_fail_jobs_with_valid_verdicts_participate(self) -> None:
        for job_verdict, overall in (("PASS", "ACCEPTED"), ("FAIL", "REWORK")):
            with self.subTest(job_verdict=job_verdict):
                findings = [] if overall == "ACCEPTED" else [_finding()]
                receipt = _participation(job_verdict=job_verdict, overall=overall, findings=findings)
                self.assertTrue(receipt["participating"])
                self.assertEqual(validate_review_round_participation(receipt)["status"], "PASS")

    def test_incomplete_or_no_final_terminal_jobs_are_resource_use_without_participation(self) -> None:
        for state in ("FAILED", "CANCELLED", "EXPIRED"):
            with self.subTest(state=state):
                request = _request()
                status = _status(request, state=state)
                result = build_external_job_result(
                    result_id=f"result-{state.lower()}",
                    request=request,
                    status=status,
                    verdict="NO_FINAL_VERDICT",
                    complete=False,
                    artifacts=[],
                    output_digest=None,
                    output_bytes=0,
                )
                receipt = build_review_round_participation(
                    reviewer_id="reviewer-a",
                    review_verdict=_verdict("ACCEPTED"),
                    findings=[],
                    job_request=request,
                    job_status=status,
                    job_result=result,
                )
                self.assertFalse(receipt["participating"])
                self.assertTrue(receipt["resourceUseObserved"])

    def test_dispositions_are_evidence_bound_immutable_and_idempotent(self) -> None:
        finding = _finding()
        confirmed = build_finding_disposition(
            finding=finding,
            disposition="CONFIRMED",
            reason_code="reproduced",
            evidence_digests=["a" * 64],
            operation_id="disposition-1",
        )
        self.assertEqual(validate_finding_disposition(confirmed)["status"], "PASS")
        self.assertEqual(merge_finding_dispositions([confirmed], [confirmed]), [confirmed])
        rejected = build_finding_disposition(
            finding=finding,
            disposition="REJECTED",
            reason_code="false-positive",
            evidence_digests=["b" * 64],
            operation_id="disposition-2",
        )
        with self.assertRaisesRegex(LifecycleError, "different terminal disposition"):
            merge_finding_dispositions([confirmed], [rejected])

    def test_tampered_participation_fails_validation(self) -> None:
        receipt = _participation(job_verdict="PASS", overall="ACCEPTED", findings=[])
        receipt["participating"] = False
        validation = validate_review_round_participation(receipt)
        self.assertEqual(validation["status"], "FAIL")

    def test_unrelated_successful_job_output_does_not_participate(self) -> None:
        verdict = _verdict("ACCEPTED")
        request = _request()
        status = _status(request)
        result = build_external_job_result(
            result_id="result-unrelated",
            request=request,
            status=status,
            verdict="PASS",
            complete=True,
            artifacts=[],
            output_digest="9" * 64,
            output_bytes=32,
        )
        receipt = build_review_round_participation(
            reviewer_id="reviewer-a",
            review_verdict=verdict,
            findings=[],
            job_request=request,
            job_status=status,
            job_result=result,
        )

        self.assertFalse(receipt["participating"])
        self.assertIn("review-verdict-job-output-mismatch", receipt["reasonCodes"])

    def test_evaluation_rejects_recomputed_forged_content(self) -> None:
        evaluation = build_review_round_evaluation(
            round_number=1,
            max_rounds=2,
            outcome="ACCEPTED",
            participating_reviewer_ids=["reviewer-a"],
            resource_use_count=1,
            finding_ids=[],
            open_blocking_finding_ids=[],
            missing_disposition_finding_ids=[],
            blockers=[],
        )
        evaluation["round"] = 2
        evaluation["maxRounds"] = 1
        evaluation["authorityClaimed"] = True
        evaluation["evaluationDigest"] = canonical_digest(
            {key: value for key, value in evaluation.items() if key != "evaluationDigest"}
        )

        validation = validate_review_round_evaluation(evaluation)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-round-budget-exceeded", {item["code"] for item in validation["blockers"]})
        self.assertIn("review-round-evaluation-authority-boundary", {item["code"] for item in validation["blockers"]})


def _participation(*, job_verdict: str, overall: str, findings: list[dict]) -> dict:
    verdict = _verdict(overall)
    request = _request()
    status = _status(request)
    result = build_external_job_result(
        result_id=f"result-{job_verdict.lower()}",
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


def _request() -> dict:
    return build_external_job_request(
        job_id="review-job",
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


def _status(request: dict, *, state: str = "SUCCEEDED") -> dict:
    return build_external_job_status(
        request=request,
        state=state,
        sequence=2,
        observed_at="2026-08-26T03:30:02Z",
        started_at="2026-08-26T03:30:00Z",
        ended_at="2026-08-26T03:30:02Z",
        process_cleanup_status="PASS",
        usage={"wallMilliseconds": 2000, "outputBytes": 0, "artifactBytes": 0},
    )


def _verdict(overall: str) -> dict:
    accepted = overall == "ACCEPTED"
    return {
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


def _finding() -> dict:
    return {"id": "F-HIGH", "severity": "HIGH", "status": "open", "message": "Blocking defect."}


if __name__ == "__main__":
    unittest.main()
