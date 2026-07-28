from __future__ import annotations

from dataclasses import dataclass
import unittest

from tools.live_hosts.common import BudgetPolicy, BudgetTracker, HarnessError


@dataclass(frozen=True)
class Usage:
    billable_tokens: int
    wall_seconds: float
    cost_usd: float | None = None


class BudgetPolicyTests(unittest.TestCase):
    def test_metered_mode_requires_usd_cap(self) -> None:
        with self.assertRaises(HarnessError) as caught:
            BudgetPolicy(mode="metered").require_authorized(allow_live=True, required_invocations=1)

        self.assertEqual(caught.exception.code, "BLOCKED_BUDGET_EXHAUSTED")
        BudgetPolicy(mode="metered", budget_cap_usd=0.01).require_authorized(allow_live=True, required_invocations=1)

    def test_subscription_and_local_modes_require_resource_caps(self) -> None:
        with self.assertRaises(HarnessError):
            BudgetPolicy(mode="subscription", max_invocations=2).require_authorized(allow_live=True, required_invocations=2)

        BudgetPolicy(mode="subscription", max_invocations=2, max_billable_tokens=100).require_authorized(
            allow_live=True,
            required_invocations=2,
        )
        BudgetPolicy(mode="local", max_invocations=2, max_wall_seconds=10).require_authorized(
            allow_live=True,
            required_invocations=2,
        )

    def test_budget_tracker_enforces_cost_token_and_time_caps_after_recording(self) -> None:
        with self.assertRaises(HarnessError):
            BudgetTracker().record(Usage(billable_tokens=10, wall_seconds=1, cost_usd=2), BudgetPolicy(mode="metered", budget_cap_usd=1))

        with self.assertRaises(HarnessError):
            BudgetTracker().record(
                Usage(billable_tokens=101, wall_seconds=1),
                BudgetPolicy(mode="subscription", max_invocations=1, max_billable_tokens=100),
            )

        with self.assertRaises(HarnessError):
            BudgetTracker().record(
                Usage(billable_tokens=1, wall_seconds=11),
                BudgetPolicy(mode="local", max_invocations=1, max_wall_seconds=10),
            )

    def test_usage_attestation_policy_distinguishes_cost_required_modes(self) -> None:
        self.assertEqual(
            BudgetPolicy(mode="metered", budget_cap_usd=1).usage_attestation_policy("host"),
            "host-usage-and-cost-required-per-invocation",
        )
        self.assertEqual(
            BudgetPolicy(mode="local", max_invocations=1, max_wall_seconds=1).usage_attestation_policy("host"),
            "host-usage-required-per-invocation-local-resource-budget",
        )


if __name__ == "__main__":
    unittest.main()
