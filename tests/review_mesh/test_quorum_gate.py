from __future__ import annotations

import unittest

from agent_lifecycle.review_mesh import build_review_mesh_assignment, build_review_mesh_profile, build_review_mesh_result, build_quorum_from_synthesis, synthesize_review_mesh_results


class ReviewMeshQuorumTests(unittest.TestCase):
    def test_quorum_passes_when_reviewer_count_and_roles_match(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        synthesis = synthesize_review_mesh_results(
            profile=profile,
            results=[
                _result(profile, "RM-1", "plan-reviewer"),
                _result(profile, "RM-2", "implementation-auditor"),
            ],
            subject={"taskId": "TASK-1", "reviewMeshRequired": True},
        )

        receipt = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 2, "requiredRoles": ["plan-reviewer"]},
            reviewer_roles=["plan-reviewer", "implementation-auditor"],
        )

        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(receipt["quorumSatisfied"])

    def test_quorum_fails_closed_when_required_role_is_missing(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        synthesis = synthesize_review_mesh_results(
            profile=profile,
            results=[_result(profile, "RM-1", "plan-reviewer")],
            subject={"taskId": "TASK-1", "reviewMeshRequired": True},
        )

        receipt = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 1, "requiredRoles": ["security-reviewer"]},
            reviewer_roles=["plan-reviewer"],
        )

        self.assertEqual(receipt["status"], "FAIL")
        self.assertFalse(receipt["quorumSatisfied"])


def _result(profile: dict, assignment_id: str, role: str) -> dict:
    assignment = build_review_mesh_assignment(
        profile=profile,
        assignment_id=assignment_id,
        subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
        reviewer={"id": assignment_id, "role": role, "modelClass": "strong-reasoning"},
        blocking=True,
    )
    return build_review_mesh_result(
        profile=profile,
        assignment=assignment,
        budget_usage={"invocations": 1, "inputTokens": 100, "outputTokens": 20, "wallSeconds": 3},
        findings=[{"id": assignment_id, "severity": "LOW", "status": "open"}],
    )


if __name__ == "__main__":
    unittest.main()
