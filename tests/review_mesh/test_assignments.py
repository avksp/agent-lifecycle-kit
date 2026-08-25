from __future__ import annotations

import unittest

from agent_lifecycle.review_mesh import (
    build_review_mesh_assignment_packet,
    build_security_verification_assignment_packet,
    source_from_intake,
    source_from_manifest,
)


class ReviewMeshAssignmentTests(unittest.TestCase):
    def test_security_assignment_is_blocking_and_independent(self) -> None:
        packet = build_security_verification_assignment_packet(
            source={
                "kind": "TASK",
                "label": "WS-01",
                "digest": "a" * 64,
                "sourceRevision": "source-1",
                "sourceLineageDigest": "b" * 64,
                "primaryProducerClass": "implementer",
                "primaryImplementationDigest": "c" * 64,
            },
            assignment_id="SEC-VERIFY-1",
            reviewer_id="security-reviewer",
            evidence_ids=["EV93-REVIEW"],
        )
        self.assertTrue(packet["assignment"]["blocking"])
        self.assertTrue(packet["assignment"]["independenceRequirement"]["required"])
        self.assertEqual(packet["securityAnalysis"]["authorityClaimed"], False)

    def test_assignment_packet_from_intake_is_host_owned_and_non_executing(self) -> None:
        source = source_from_intake(
            {
                "schemaVersion": "agent-adapter-task-start-receipt.v1",
                "status": "REVIEW_REQUIRED",
                "adapterId": "codex",
                "input": {"label": "task.md"},
                "receiptDigest": "a" * 64,
            }
        )

        packet = build_review_mesh_assignment_packet(
            source=source,
            mode="leader-draft-multi-review",
            phase="plan-review",
            assignment_id="RM-1",
            reviewer_id="reviewer-a",
            reviewer_role="plan-reviewer",
            blocking=False,
        )

        self.assertEqual(packet["schemaVersion"], "agent-review-mesh-reviewer-packet.v1")
        self.assertEqual(packet["assignment"]["schemaVersion"], "agent-review-mesh-assignment.v1")
        self.assertTrue(packet["reviewerTask"]["hostOwnedExecution"])
        self.assertFalse(packet["reviewerTask"]["alkCoreLaunchAllowed"])
        self.assertFalse(packet["reviewerTask"]["promptAuthorityGranted"])

    def test_blocking_manifest_assignment_requires_plan_opt_in_from_source(self) -> None:
        source = source_from_manifest(
            {
                "schemaVersion": "agent-plan-manifest.v1",
                "status": "FROZEN",
                "package": {"id": "release-x"},
                "reviewMesh": {"required": True},
            }
        )

        packet = build_review_mesh_assignment_packet(
            source=source,
            mode="implementation-audit-panel",
            phase="implementation-audit",
            assignment_id="RM-2",
            reviewer_id="reviewer-b",
            reviewer_role="implementation-auditor",
            blocking=True,
        )

        self.assertTrue(packet["assignment"]["blocking"])
        self.assertTrue(packet["assignment"]["subject"]["reviewMeshBlockingOptIn"])

    def test_manifest_source_carries_base_revision_lineage(self) -> None:
        source = source_from_manifest(
            {
                "schemaVersion": "agent-plan-manifest.v1",
                "status": "FROZEN",
                "package": {"id": "release-x"},
                "baseRevision": {"ref": "main", "sha": "a" * 40},
            }
        )

        self.assertEqual(source["sourceRevision"], "a" * 40)
        self.assertEqual(len(source["sourceLineageDigest"]), 64)
        self.assertEqual(source["primaryProducerClass"], "plan-authority")


if __name__ == "__main__":
    unittest.main()
