from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.quality import (
    build_cross_check_profile,
    build_cross_check_receipt,
    require_cross_check_receipt_pass,
    validate_cross_check_profile,
    validate_cross_check_receipt,
)


class CrossCheckProfileTests(unittest.TestCase):
    def test_default_profile_is_optional_advisory_and_budget_capped(self) -> None:
        profile = build_cross_check_profile()

        validation = validate_cross_check_profile(profile)

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(profile["enabledByDefault"])
        self.assertTrue(profile["advisoryByDefault"])
        self.assertEqual(profile["budgetUnits"], "tokens-and-resources")
        self.assertFalse(profile["monetaryCostCanonical"])

    def test_cross_check_receipt_passes_within_budget(self) -> None:
        profile = build_cross_check_profile()
        receipt = build_cross_check_receipt(
            profile=profile,
            subject={"taskId": "WS22-03", "patchDigest": "a" * 64},
            reviewer={"host": "secondary-reviewer", "modelClass": "review"},
            budget_usage={"invocations": 1, "inputTokens": 1000, "outputTokens": 200, "wallSeconds": 20},
            findings=[],
        )

        validation = validate_cross_check_receipt(receipt, profile=profile)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(receipt["advisory"])
        self.assertEqual(require_cross_check_receipt_pass(validation), validation)

    def test_budget_cap_and_blocking_without_plan_opt_in_fail(self) -> None:
        profile = build_cross_check_profile(budget_cap={"maxInvocations": 1, "maxInputTokens": 100, "maxOutputTokens": 100, "maxWallSeconds": 10})
        receipt = build_cross_check_receipt(
            profile=profile,
            subject={"taskId": "WS22-03"},
            reviewer={"host": "secondary-reviewer"},
            budget_usage={"invocations": 2, "inputTokens": 101, "outputTokens": 1, "wallSeconds": 1},
            blocking=True,
        )

        validation = validate_cross_check_receipt(receipt, profile=profile)

        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("cross-check-budget-cap-exceeded", codes)
        self.assertIn("cross-check-blocking-without-plan-opt-in", codes)
        with self.assertRaises(LifecycleError):
            require_cross_check_receipt_pass(validation)

    def test_money_caps_are_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            build_cross_check_profile(budget_cap={"maxInvocations": 1, "maxUsd": 1})


if __name__ == "__main__":
    unittest.main()
