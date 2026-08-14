from __future__ import annotations

import copy
import unittest

from agent_lifecycle.planning.deltas import build_plan_delta, validate_plan_delta


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


class PlanDeltaTests(unittest.TestCase):
    def test_authority_change_requires_review_and_lock(self) -> None:
        before = _manifest()
        after = _manifest(2, "changed")
        delta = build_plan_delta(before, after)
        self.assertEqual(delta["status"], "PASS")
        self.assertTrue(delta["reviewRequired"])
        self.assertTrue(delta["newLockRequired"])
        self.assertEqual(validate_plan_delta(delta)["status"], "PASS")

    def test_unchanged_authority_does_not_require_review(self) -> None:
        delta = build_plan_delta(_manifest(), _manifest(2))
        self.assertFalse(delta["reviewRequired"])
        self.assertFalse(delta["newLockRequired"])

    def test_delta_is_read_only(self) -> None:
        before = _manifest()
        after = copy.deepcopy(before)
        after["planRevision"] = 2
        build_plan_delta(before, after)
        self.assertEqual(before["planRevision"], 1)


if __name__ == "__main__":
    unittest.main()
