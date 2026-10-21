from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.quality.cross_check import validate_cross_check_receipt
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
from agent_lifecycle.review_mesh.contracts import require_review_mesh_quorum_pass


def session_review_inputs(max_invocations: int = 2) -> tuple[dict, dict, dict]:
    from tests.contracts.test_external_job_schemas import session_fixture

    profile = build_review_mesh_profile(
        independence_required=False,
        budget_cap={"maxInputTokens": 12000, "maxOutputTokens": 4000,
                    "maxInvocations": max_invocations, "maxWallSeconds": 180},
    )
    subject = {"taskId": "SESSION-REVIEW", "sourceRevision": "b" * 40,
               "sessionDigest": "a" * 64, "cumulativeUsageRequired": True}
    assignment = build_review_mesh_assignment(
        profile=profile, assignment_id="SESSION-ASSIGNMENT", subject=subject,
        reviewer={"role": "reviewer", "modelClass": "strong-reasoning"},
    )
    receipt, _, proof = session_fixture()
    binding = {"subjectDigest": canonical_digest(subject), "assignmentDigest": assignment["assignmentDigest"]}
    receipt.update(binding)
    receipt["receiptDigest"] = canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"})
    proof.update(binding, receiptDigest=receipt["receiptDigest"])
    return profile, assignment, {"receipt": receipt, "qualification": proof}


class ReviewerSessionBudgetTests(unittest.TestCase):
    def test_cumulative_invocations_overrun_is_not_hidden_by_a_single_result(self) -> None:
        profile, assignment, context = session_review_inputs(1)
        usage = {key: context["receipt"]["usage"][key] for key in ("invocations", "inputTokens", "outputTokens", "wallSeconds")}
        with self.assertRaises(LifecycleError):
            build_review_mesh_result(profile=profile, assignment=assignment, status="PASS",
                                     budget_usage=usage, session_usage_context=context)

    def test_cumulative_budget_needs_separately_bound_source_and_assignment(self) -> None:
        profile, assignment, context = session_review_inputs()
        usage = {key: context["receipt"]["usage"][key] for key in ("invocations", "inputTokens", "outputTokens", "wallSeconds")}
        with self.assertRaises(LifecycleError):
            build_review_mesh_result(profile=profile, assignment=assignment, budget_usage=usage, status="PASS")
        result = build_review_mesh_result(profile=profile, assignment=assignment, budget_usage=usage,
                                          status="PASS", session_usage_context=context)
        self.assertEqual(result["sessionBudgetBasis"], "CUMULATIVE_PROVIDER_SESSION")
        self.assertEqual(validate_review_mesh_result(result, profile=profile, assignment=assignment,
                                                     session_usage_context=context)["status"], "PASS")
        self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "FAIL")

    def test_prompt_size_usage_cannot_replace_session_totals(self) -> None:
        profile, assignment, context = session_review_inputs()
        with self.assertRaises(LifecycleError):
            build_review_mesh_result(profile=profile, assignment=assignment, status="PASS",
                                     budget_usage={"invocations": 1, "inputTokens": 10, "outputTokens": 4, "wallSeconds": 1},
                                     session_usage_context=context)

    def test_missing_provider_usage_or_wrong_attestation_refuses(self) -> None:
        for key in ("receiptDigest", "sessionDigest", "sourceArtifactDigest", "assignmentDigest"):
            profile, assignment, context = session_review_inputs()
            context["qualification"][key] = "f" * 64
            usage = {key: context["receipt"]["usage"][key] for key in ("invocations", "inputTokens", "outputTokens", "wallSeconds")}
            with self.assertRaises(LifecycleError):
                build_review_mesh_result(profile=profile, assignment=assignment, status="PASS",
                                         budget_usage=usage, session_usage_context=context)


class ReviewMeshContractTests(unittest.TestCase):
    def test_supplied_profile_modes_bind_result_synthesis_and_quorum_acceptance(self) -> None:
        allowed, excluded = "leader-draft-multi-review", "parallel-research-synthesis"
        profile = build_review_mesh_profile(modes=[allowed], independence_required=False)
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="MODE-BOUND",
            subject={"taskId": "TASK-1"},
            reviewer={"role": "reviewer", "modelClass": "strong-reasoning"},
        )
        result = build_review_mesh_result(
            profile=profile,
            assignment=assignment,
            budget_usage={"invocations": 1, "inputTokens": 11, "outputTokens": 1, "wallSeconds": 1},
            status="PASS",
        )
        synthesis = build_review_mesh_synthesis(
            profile=profile, mode=allowed, subject={"taskId": "TASK-1"}, result_digests=[result["resultDigest"]]
        )
        quorum = build_review_mesh_quorum_receipt(
            profile=profile,
            mode=allowed,
            subject={"reviewMeshRequired": True},
            quorum_policy={"minReviewers": 1, "requiredRoles": []},
            reviewer_count=1,
        )
        require_review_mesh_quorum_pass(validate_review_mesh_quorum_receipt(quorum, profile=profile))
        for name, receipt, validator, digest in [
            ("result", result, validate_review_mesh_result, "resultDigest"),
            ("synthesis", synthesis, validate_review_mesh_synthesis, "synthesisDigest"),
            ("quorum", quorum, validate_review_mesh_quorum_receipt, "receiptDigest"),
        ]:
            with self.subTest(consumer=name):
                self.assertEqual(validator(receipt, profile=profile)["status"], "PASS")
                mutant = deepcopy(receipt)
                mutant["mode"] = excluded
                _repair(mutant, digest)
                self.assertEqual(validator(mutant)["status"], "PASS")
                validation = validator(mutant, profile=profile)
                self.assertIn(f"review-mesh-{name}-mode-not-profile", {b["code"] for b in validation["blockers"]})
                self.assertEqual(validation["status"], "FAIL")
                if name == "quorum":
                    with self.assertRaises(LifecycleError):
                        require_review_mesh_quorum_pass(validation)

    def test_direct_result_validation_rejects_conflicting_whole_profile(self) -> None:
        profile, _assignment, result = _direct_result(live_calls=True)
        self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "PASS")
        for field in ["liveCallsAllowed", "budgetCap"]:
            with self.subTest(field=field):
                bad = deepcopy(profile)
                if field == "liveCallsAllowed":
                    bad[field] = False
                else:
                    bad[field]["maxInputTokens"] = 0
                _repair(bad, "profileDigest")
                value = deepcopy(result)
                value["profileDigest"] = bad["profileDigest"]
                _repair(value, "resultDigest")
                validation = validate_review_mesh_result(value, profile=bad)
                self.assertIn("review-mesh-profile-invalid", {b["code"] for b in validation["blockers"]})

    def test_profile_labels_join_assignment_result_and_cross_receipt(self) -> None:
        profile, assignment, result = _direct_result()
        assignment["profileId"] = "OTHER"
        _repair(assignment, "assignmentDigest")
        validation = validate_review_mesh_assignment(assignment, profile=profile)
        self.assertIn("review-mesh-assignment-profile-id-mismatch", {b["code"] for b in validation["blockers"]})
        result["profileId"] = "OTHER"
        _repair(result, "resultDigest")
        validation = validate_review_mesh_result(result, profile=profile)
        self.assertIn("review-mesh-result-profile-id-mismatch", {b["code"] for b in validation["blockers"]})
        cross = deepcopy(result["crossCheckReceipt"])
        cross["profileId"] = "OTHER"
        _repair(cross, "receiptDigest")
        validation = validate_cross_check_receipt(cross, profile=profile["crossCheckProfile"])
        self.assertIn("cross-check-profile-id-mismatch", {b["code"] for b in validation["blockers"]})

    def test_quorum_pass_rejects_valid_failed_receipt_and_forged_count_roles(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        failed = build_review_mesh_quorum_receipt(
            profile=profile,
            mode=profile["defaultMode"],
            subject={"reviewMeshRequired": True},
            quorum_policy={"minReviewers": 2, "requiredRoles": []},
            reviewer_count=2,
            blocking_findings_unresolved=True,
        )
        validation = validate_review_mesh_quorum_receipt(failed, profile=profile)
        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertEqual(validation["receiptStatus"], "FAIL")
        with self.assertRaises(LifecycleError):
            require_review_mesh_quorum_pass(validation)
        positive = build_review_mesh_quorum_receipt(
            profile=profile,
            mode=profile["defaultMode"],
            subject={"reviewMeshRequired": True},
            quorum_policy={"minReviewers": 2, "requiredRoles": []},
            reviewer_count=2,
        )
        require_review_mesh_quorum_pass(validate_review_mesh_quorum_receipt(positive, profile=profile))
        for field, value in [
            ("reviewerCount", 1),
            ("requiredRolesSatisfied", False),
            ("blockingFindingsUnresolved", True),
        ]:
            with self.subTest(field=field):
                mutant = deepcopy(positive)
                mutant[field] = value
                _repair(mutant, "receiptDigest")
                validation = validate_review_mesh_quorum_receipt(mutant, profile=profile)
                self.assertEqual(validation["status"], "FAIL")
                with self.assertRaises(LifecycleError):
                    require_review_mesh_quorum_pass(validation)

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


def _repair(value: dict, key: str) -> None:
    value[key] = canonical_digest({k: v for k, v in value.items() if k != key})


def _direct_result(*, live_calls: bool = False) -> tuple[dict, dict, dict]:
    profile = build_review_mesh_profile(independence_required=False, live_calls_allowed=live_calls)
    assignment = build_review_mesh_assignment(
        profile=profile,
        assignment_id="DIRECT",
        subject={"taskId": "TASK"},
        reviewer={"role": "reviewer", "modelClass": "strong-reasoning"},
    )
    result = build_review_mesh_result(
        profile=profile,
        assignment=assignment,
        budget_usage={"invocations": 1, "inputTokens": 11, "outputTokens": 1, "wallSeconds": 1},
        status="PASS",
        live_calls_started=live_calls,
    )
    return profile, assignment, result


if __name__ == "__main__":
    unittest.main()
