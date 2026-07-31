from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.runner import build_sandbox_receipt
from agent_lifecycle.workflow import (
    build_sandbox_requirement_policy,
    require_task_sandbox_evidence_pass,
    sandbox_evidence_required,
    validate_task_sandbox_evidence,
)


class SandboxPolicyTests(unittest.TestCase):
    def test_low_risk_task_does_not_require_sandbox_receipt(self) -> None:
        task = {"id": "WS20-low", "tier": "S1"}

        validation = validate_task_sandbox_evidence(task, receipt=None)

        self.assertFalse(sandbox_evidence_required(task))
        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(validation["required"])

    def test_high_risk_task_fails_closed_when_receipt_missing(self) -> None:
        task = {"id": "WS20-high", "tier": "S2"}

        validation = validate_task_sandbox_evidence(task, receipt=None)

        self.assertTrue(validation["required"])
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("sandbox-receipt-required", {item["code"] for item in validation["blockers"]})
        with self.assertRaises(LifecycleError):
            require_task_sandbox_evidence_pass(validation)

    def test_unknown_receipt_does_not_satisfy_required_high_risk_task(self) -> None:
        task = {"id": "WS20-high", "tier": "S2"}
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS20-high",
            attempt=1,
            boundaries=_unknown_boundaries(),
            enforcement={"source": "UNKNOWN", "verified": False, "evidenceIds": [], "details": {}},
            verifier={"tool": "unit-test"},
        )

        validation = validate_task_sandbox_evidence(task, receipt=receipt, expected_lineage=_lineage(), attempt=1)

        self.assertEqual(validation["status"], "FAIL")
        self.assertEqual(validation["sandboxStatus"], "UNKNOWN")
        self.assertIn("sandbox-receipt-not-accepted", {item["code"] for item in validation["blockers"]})

    def test_pass_receipt_satisfies_required_high_risk_task(self) -> None:
        task = {"id": "WS20-high", "riskFlags": {"security": True}}
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS20-high",
            attempt=1,
            boundaries=_enforced_boundaries(),
            enforcement={"source": "HOST", "verified": True, "evidenceIds": ["ev-sandbox"], "details": {}},
            verifier={"tool": "unit-test"},
        )

        validation = validate_task_sandbox_evidence(task, receipt=receipt, expected_lineage=_lineage(), attempt=1)

        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(validation["required"])
        self.assertEqual(validation["sandboxStatus"], "PASS")

    def test_explicit_task_policy_requires_receipt_for_low_risk_task(self) -> None:
        task = {"id": "WS20-explicit", "tier": "S1", "executionPolicy": {"sandbox": {"required": True}}}

        validation = validate_task_sandbox_evidence(task, receipt=None)

        self.assertTrue(validation["required"])
        self.assertEqual(validation["status"], "FAIL")

    def test_policy_can_be_disabled(self) -> None:
        task = {"id": "WS20-high", "tier": "S2"}
        policy = build_sandbox_requirement_policy(mode="off")

        validation = validate_task_sandbox_evidence(task, receipt=None, policy=policy)

        self.assertFalse(validation["required"])
        self.assertEqual(validation["status"], "PASS")


def _lineage() -> dict:
    return {
        "runId": "run-1",
        "packageId": "release-1-10",
        "planRevision": 4,
        "planDigest": "a" * 64,
        "sourceRevision": "b" * 40,
    }


def _enforced_boundaries() -> dict:
    return {
        name: {"mode": "ENFORCED", "evidenceIds": [f"ev-{name}"], "details": {}}
        for name in ("filesystem", "network", "process", "environment")
    }


def _unknown_boundaries() -> dict:
    return {
        name: {"mode": "UNKNOWN", "evidenceIds": [], "details": {}}
        for name in ("filesystem", "network", "process", "environment")
    }


if __name__ == "__main__":
    unittest.main()
