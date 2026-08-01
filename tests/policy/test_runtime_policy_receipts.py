from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.policy import (
    build_runtime_policy_receipt,
    require_runtime_policy_receipt_pass,
    validate_runtime_policy_receipt,
)


class RuntimePolicyReceiptTests(unittest.TestCase):
    def test_enforced_receipt_requires_pre_execution_evidence(self) -> None:
        receipt = build_runtime_policy_receipt(
            policy_id="network-egress",
            action="DENY",
            subject={"taskId": "WS-01", "capability": "network"},
            adapter_evidence={
                "preExecutionEnforcement": True,
                "decisionRecordedBeforeExecution": True,
                "source": "host-protocol-envelope",
            },
            enforcement_mode="enforced",
            evidence_ids=["adapter-event-1"],
        )

        validation = validate_runtime_policy_receipt(receipt)

        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(receipt["enforcementClaimed"])
        self.assertFalse(receipt["advisoryOnly"])
        self.assertEqual(require_runtime_policy_receipt_pass(validation), validation)

    def test_advisory_receipt_does_not_claim_blocking_enforcement(self) -> None:
        receipt = build_runtime_policy_receipt(
            policy_id="shell-command-review",
            action="ASK",
            subject={"taskId": "WS-02", "capability": "shell"},
            adapter_evidence={
                "preExecutionEnforcement": False,
                "decisionRecordedBeforeExecution": False,
                "postFactumOnly": True,
            },
        )

        validation = validate_runtime_policy_receipt(receipt)

        self.assertEqual(receipt["status"], "PASS")
        self.assertFalse(receipt["enforcementClaimed"])
        self.assertTrue(receipt["advisoryOnly"])
        self.assertEqual(validation["status"], "PASS")

    def test_enforcement_claim_without_adapter_evidence_fails_closed(self) -> None:
        receipt = build_runtime_policy_receipt(
            policy_id="file-write-policy",
            action="ALLOW",
            subject={"taskId": "WS-03", "capability": "write-file"},
            adapter_evidence={
                "preExecutionEnforcement": False,
                "decisionRecordedBeforeExecution": False,
                "postFactumOnly": True,
            },
            enforcement_mode="enforced",
        )

        validation = validate_runtime_policy_receipt(receipt)

        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("runtime-policy-enforcement-unproven", {item["code"] for item in validation["blockers"]})
        with self.assertRaises(LifecycleError):
            require_runtime_policy_receipt_pass(validation)


if __name__ == "__main__":
    unittest.main()
