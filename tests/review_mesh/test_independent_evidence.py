from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.independent_evidence_schemas import (
    build_independence_requirement,
    build_independent_evidence,
)
from agent_lifecycle.review_mesh.assignments import build_review_mesh_assignment_packet
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_profile,
    build_review_mesh_result,
    validate_review_mesh_quorum_receipt,
    validate_review_mesh_result,
)
from agent_lifecycle.review_mesh.quorum import build_quorum_from_synthesis


class ReviewMeshIndependentEvidenceTests(unittest.TestCase):
    def test_assignment_and_quorum_carry_required_independence(self) -> None:
        requirement = build_independence_requirement(prohibited_producer_classes=["implementation-worker"])
        source = {
            "kind": "PLAN_CRITERION",
            "label": "AC-IND-1",
            "digest": "a" * 64,
            "sourceRevision": "source-revision-1",
            "sourceLineageDigest": "b" * 64,
            "primaryProducerClass": "implementation-worker",
            "primaryImplementationDigest": "c" * 64,
        }
        packet = build_review_mesh_assignment_packet(
            source=source,
            mode="implementation-audit-panel",
            phase="criterion-review",
            assignment_id="assignment-ind-1",
            reviewer_id="reviewer-ind-1",
            reviewer_role="independent-reviewer",
            reviewer_producer_class="independent-reviewer",
            independence_requirement=requirement,
        )
        assignment = packet["assignment"]
        evidence = build_independent_evidence(
            evidence_id="EV-IND-1",
            criterion_id="AC-IND-1",
            requirement=requirement,
            source_revision="source-revision-1",
            source_lineage_digest="b" * 64,
            method="deterministic-check",
            producer_class="independent-reviewer",
            producer_identity_hash="d" * 64,
            implementation_digest="e" * 64,
        )
        profile = build_review_mesh_profile(default_mode="implementation-audit-panel", independence_required=False)
        synthesis = {
            "mode": "implementation-audit-panel",
            "subject": assignment["subject"],
            "resultDigests": ["f" * 64],
            "unresolvedFindings": [],
        }

        receipt = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 1, "requiredRoles": ["independent-reviewer"]},
            reviewer_roles=["independent-reviewer"],
            independence_requirement=requirement,
            independent_evidence=[evidence],
        )

        self.assertEqual(assignment["independenceRequirement"], requirement)
        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(receipt["quorumSatisfied"])
        self.assertEqual(receipt["independentEvidence"][0]["evidenceDigest"], evidence["evidenceDigest"])

    def test_quorum_does_not_block_when_requirement_is_absent(self) -> None:
        profile = build_review_mesh_profile(default_mode="implementation-audit-panel", independence_required=False)
        synthesis = {
            "mode": "implementation-audit-panel",
            "subject": {"reviewMeshRequired": False},
            "resultDigests": [canonical_digest({"result": 1})],
            "unresolvedFindings": [],
        }

        receipt = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 1, "requiredRoles": []},
            reviewer_roles=[],
        )

        self.assertEqual(receipt["status"], "PASS")

    def test_optional_quorum_does_not_block_when_evidence_is_missing(self) -> None:
        requirement = build_independence_requirement(required=False)
        profile = build_review_mesh_profile(default_mode="implementation-audit-panel", independence_required=False)
        synthesis = {
            "mode": "implementation-audit-panel",
            "subject": {"reviewMeshRequired": False},
            "resultDigests": [canonical_digest({"result": 1})],
            "unresolvedFindings": [],
        }

        receipt = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 1, "requiredRoles": []},
            reviewer_roles=[],
            independence_requirement=requirement,
        )

        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["independentEvidence"], [])
        self.assertEqual(validate_review_mesh_quorum_receipt(receipt, profile=profile)["status"], "PASS")

    def test_required_quorum_evidence_cannot_be_skipped_with_review_mesh_disabled(self) -> None:
        requirement = build_independence_requirement()
        profile = build_review_mesh_profile(default_mode="implementation-audit-panel", independence_required=False)
        synthesis = {
            "mode": "implementation-audit-panel",
            "subject": {"reviewMeshRequired": False},
            "resultDigests": [canonical_digest({"result": 1})],
            "unresolvedFindings": [],
        }

        receipt = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 1, "requiredRoles": []},
            reviewer_roles=[],
            independence_requirement=requirement,
        )

        self.assertEqual(receipt["status"], "FAIL")
        self.assertIn(
            "review-mesh-quorum-independent-evidence-required",
            {item["code"] for item in receipt["blockers"]},
        )

    def test_required_evidence_blocks_result_before_synthesis(self) -> None:
        requirement = build_independence_requirement()
        profile = build_review_mesh_profile(default_mode="implementation-audit-panel", independence_required=False)
        assignment = build_review_mesh_assignment_packet(
            source={
                "kind": "PLAN_CRITERION",
                "label": "AC-IND-2",
                "digest": "a" * 64,
                "sourceRevision": "source-revision-1",
                "sourceLineageDigest": "b" * 64,
                "primaryProducerClass": "implementation-worker",
                "primaryImplementationDigest": "c" * 64,
            },
            mode="implementation-audit-panel",
            phase="criterion-review",
            assignment_id="assignment-ind-2",
            reviewer_id="reviewer-ind-2",
            reviewer_role="independent-reviewer",
            reviewer_producer_class="independent-reviewer",
            independence_requirement=requirement,
            profile=profile,
        )["assignment"]

        result = build_review_mesh_result(
            profile=profile,
            assignment=assignment,
            budget_usage={"invocations": 0, "inputTokens": 0, "outputTokens": 0, "wallSeconds": 0},
        )

        validation = validate_review_mesh_result(result, profile=profile)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "review-mesh-result-independent-evidence-required",
            {item["code"] for item in validation["blockers"]},
        )


if __name__ == "__main__":
    unittest.main()
