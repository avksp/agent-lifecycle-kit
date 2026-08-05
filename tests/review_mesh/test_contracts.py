from __future__ import annotations

import unittest

from agent_lifecycle.review_mesh import (
    build_review_mesh_assignment,
    build_review_mesh_profile,
    build_review_mesh_quorum_receipt,
    build_review_mesh_result,
    build_review_mesh_synthesis,
    validate_review_mesh_assignment,
    validate_review_mesh_profile,
    validate_review_mesh_quorum_receipt,
    validate_review_mesh_result,
    validate_review_mesh_synthesis,
)


class ReviewMeshContractTests(unittest.TestCase):
    def test_profile_reuses_cross_check_budget_and_independence_semantics(self) -> None:
        profile = build_review_mesh_profile(
            budget_cap={"maxInvocations": 2, "maxInputTokens": 8000, "maxOutputTokens": 2000, "maxWallSeconds": 300},
            reviewer_model_classes=["strong-reasoning", "local-strong-review"],
        )

        validation = validate_review_mesh_profile(profile)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertEqual(profile["budgetUnits"], "tokens-and-resources")
        self.assertEqual(profile["budgetCap"], profile["crossCheckProfile"]["budgetCap"])
        self.assertEqual(profile["independencePolicy"], profile["crossCheckProfile"]["independencePolicy"])
        self.assertFalse(profile["concreteProviderModelNamesInPortableContract"])

    def test_profile_rejects_monetary_budget_fields(self) -> None:
        profile = build_review_mesh_profile()
        profile["budgetCap"] = {**profile["budgetCap"], "costUsd": 1}
        profile["profileDigest"] = "0" * 64

        validation = validate_review_mesh_profile(profile)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-mesh-money-cap-not-allowed", {item["code"] for item in validation["blockers"]})
        self.assertIn("review-mesh-monetary-field-not-allowed", {item["code"] for item in validation["blockers"]})

    def test_blocking_assignment_requires_reviewed_plan_opt_in(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="RM-1",
            subject={"taskId": "TASK-1"},
            reviewer={"role": "plan-reviewer", "modelClass": "strong-reasoning"},
            blocking=True,
        )

        validation = validate_review_mesh_assignment(assignment, profile=profile)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-mesh-blocking-without-plan-opt-in", {item["code"] for item in validation["blockers"]})

    def test_independence_is_proven_with_neutral_identity_hashes(self) -> None:
        profile = build_review_mesh_profile(independence_required=True)
        subject = {
            "taskId": "TASK-1",
            "reviewMeshBlockingOptIn": True,
            "hostIdentityHash": "a" * 64,
            "modelIdentityHash": "b" * 64,
        }
        reviewer = {
            "role": "plan-reviewer",
            "modelClass": "strong-reasoning",
            "hostIdentityHash": "c" * 64,
            "modelIdentityHash": "d" * 64,
        }
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="RM-2",
            subject=subject,
            reviewer=reviewer,
            blocking=True,
        )

        validation = validate_review_mesh_assignment(assignment, profile=profile)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])

    def test_missing_independence_evidence_fails_when_required(self) -> None:
        profile = build_review_mesh_profile(independence_required=True)
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="RM-3",
            subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
            reviewer={"role": "plan-reviewer", "modelClass": "strong-reasoning"},
            blocking=True,
        )

        validation = validate_review_mesh_assignment(assignment, profile=profile)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-mesh-cross-check-probe-failed", {item["code"] for item in validation["blockers"]})

    def test_provider_model_names_are_not_portable_identity(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="RM-4",
            subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
            reviewer={"role": "plan-reviewer", "modelClass": "strong-reasoning", "providerModel": "example-model"},
            blocking=True,
        )

        validation = validate_review_mesh_assignment(assignment, profile=profile)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-mesh-provider-model-name-not-portable", {item["code"] for item in validation["blockers"]})

    def test_result_reuses_cross_check_receipt_and_budget_caps(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="RM-5",
            subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
            reviewer={"role": "plan-reviewer", "modelClass": "local-strong-review"},
            blocking=True,
        )
        result = build_review_mesh_result(
            profile=profile,
            assignment=assignment,
            budget_usage={"invocations": 1, "inputTokens": 2000, "outputTokens": 400, "wallSeconds": 60},
            findings=[{"id": "F1", "severity": "LOW"}],
        )

        validation = validate_review_mesh_result(result, profile=profile)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertEqual(result["crossCheckReceipt"]["schemaVersion"], "agent-cross-check-receipt.v1")
        self.assertEqual(result["independence"], result["crossCheckReceipt"]["independence"])

    def test_synthesis_and_quorum_receipts_are_digest_validated(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        synthesis = build_review_mesh_synthesis(
            profile=profile,
            mode="parallel-research-synthesis",
            subject={"taskId": "TASK-1"},
            result_digests=["e" * 64, "f" * 64],
            agreement=[{"findingKey": "A"}],
        )
        quorum = build_review_mesh_quorum_receipt(
            profile=profile,
            mode="parallel-research-synthesis",
            subject={"taskId": "TASK-1", "reviewMeshRequired": True},
            quorum_policy={"minReviewers": 2, "requiredRoles": []},
            reviewer_count=2,
        )

        self.assertEqual(validate_review_mesh_synthesis(synthesis, profile=profile)["status"], "PASS")
        self.assertEqual(validate_review_mesh_quorum_receipt(quorum, profile=profile)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
