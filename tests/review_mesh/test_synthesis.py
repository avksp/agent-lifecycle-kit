from __future__ import annotations

import unittest

from agent_lifecycle.review_mesh import build_review_mesh_assignment, build_review_mesh_profile, build_review_mesh_result, synthesize_review_mesh_results


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

        synthesis = synthesize_review_mesh_results(profile=profile, results=[first, second], rejected_finding_ids=["F1"])

        self.assertEqual(synthesis["status"], "PASS")
        self.assertEqual([item["id"] for item in synthesis["rejectedFindings"]], ["F1"])
        self.assertEqual(synthesis["acceptedFindings"], [])


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


if __name__ == "__main__":
    unittest.main()
