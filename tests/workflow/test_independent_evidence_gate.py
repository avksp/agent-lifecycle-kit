from __future__ import annotations

import unittest

from agent_lifecycle.contracts.independent_evidence_schemas import (
    build_independence_requirement,
    build_independent_evidence,
)
from agent_lifecycle.workflow.review_mesh_gate import validate_review_mesh_quorum_gate


class IndependentEvidenceGateTests(unittest.TestCase):
    def test_required_criterion_blocks_without_independent_evidence(self) -> None:
        requirement = build_independence_requirement()

        gate = validate_review_mesh_quorum_gate(
            phase="criterion-review",
            config=None,
            independence_requirement=requirement,
        )

        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("review-mesh-independent-evidence-required", {item["code"] for item in gate["blockers"]})

    def test_required_criterion_passes_with_bounded_evidence(self) -> None:
        requirement = build_independence_requirement()
        evidence = build_independent_evidence(
            evidence_id="EV-GATE-1",
            criterion_id="AC-GATE-1",
            requirement=requirement,
            source_revision="source-revision-1",
            source_lineage_digest="1" * 64,
            method="deterministic-check",
            producer_class="independent-reviewer",
            producer_identity_hash="2" * 64,
            implementation_digest="3" * 64,
        )

        gate = validate_review_mesh_quorum_gate(
            phase="criterion-review",
            config=None,
            independence_requirement=requirement,
            independent_evidence=[evidence],
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["independence"][0]["independenceStatus"], "REQUIRED_PASS")

    def test_optional_criterion_remains_advisory(self) -> None:
        requirement = build_independence_requirement(required=False)

        gate = validate_review_mesh_quorum_gate(
            phase="criterion-review",
            config=None,
            independence_requirement=requirement,
        )

        self.assertEqual(gate["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
