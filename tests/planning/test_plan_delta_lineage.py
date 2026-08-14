from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.planning.deltas import build_plan_delta


def _manifest(revision: int = 1, description: str = "same") -> dict:
    return {
        "package": {"id": "sample"},
        "planRevision": revision,
        "status": "FROZEN",
        "baseRevision": {"ref": "main", "sha": "a" * 40},
        "specification": {"requirements": [{"id": "R1", "description": description}], "tier": "S1"},
        "workstreams": [{"id": "WS1", "writes": ["src/example.py"], "evidenceIds": ["EV1"]}],
        "acceptance": {"criteria": [{"id": "AC1"}]},
        "validation": {"extraEvidence": ["EV1"]},
        "budgetPolicy": {"modelTokenBudget": 0},
        "securityGates": ["offline"],
        "finalAuditGates": ["review"],
    }


class PlanDeltaLineageTests(unittest.TestCase):
    def test_mismatched_lock_blocks_delta(self) -> None:
        before = _manifest()
        after = _manifest(2, "changed")
        result = build_plan_delta(
            before,
            after,
            before_lock={"manifestHash": "0" * 64},
            after_lock={"manifestHash": canonical_digest(after)},
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("plan-delta-lock-source-mismatch", {item["code"] for item in result["blockers"]})

    def test_package_identity_must_be_stable(self) -> None:
        before = _manifest()
        after = _manifest(2)
        after["package"]["id"] = "other"
        result = build_plan_delta(before, after)
        self.assertEqual(result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
