from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, write_json_create
from agent_lifecycle.review_mesh import build_review_mesh_profile, build_review_mesh_quorum_receipt
from agent_lifecycle.workflow.review_mesh_gate import require_review_mesh_quorum_gate_pass, validate_review_mesh_quorum_gate, validate_review_mesh_quorum_path


class ReviewMeshWorkflowGateTests(unittest.TestCase):
    def test_optional_gate_passes_without_receipt(self) -> None:
        gate = validate_review_mesh_quorum_gate(phase="plan-review", config=None)

        self.assertEqual(gate["status"], "PASS")
        self.assertFalse(gate["required"])

    def test_required_gate_fails_without_receipt(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        gate = validate_review_mesh_quorum_gate(
            phase="implementation-audit",
            config={"required": True, "phases": ["implementation-audit"], "profileDigest": profile["profileDigest"]},
        )

        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("review-mesh-quorum-receipt-missing", {item["code"] for item in gate["blockers"]})
        with self.assertRaises(LifecycleError):
            require_review_mesh_quorum_gate_pass(gate)

    def test_required_gate_accepts_matching_receipt_path(self) -> None:
        profile = build_review_mesh_profile(independence_required=False)
        receipt = build_review_mesh_quorum_receipt(
            profile=profile,
            mode=profile["defaultMode"],
            subject={"taskId": "TASK-1", "reviewMeshRequired": True},
            quorum_policy={"minReviewers": 1, "requiredRoles": []},
            reviewer_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "work/review-mesh/quorum.json", receipt)

            gate = validate_review_mesh_quorum_path(
                root=root,
                phase="implementation-audit",
                config={"required": True, "phases": ["implementation-audit"], "profileDigest": profile["profileDigest"]},
                receipt_path="work/review-mesh/quorum.json",
            )

        self.assertEqual(gate["status"], "PASS", json.dumps(gate["blockers"]))
        self.assertTrue(gate["receipt"]["path"].endswith("work/review-mesh/quorum.json"))


if __name__ == "__main__":
    unittest.main()
