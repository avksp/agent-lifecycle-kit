from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.policy.thread_bridge import (
    build_default_thread_bridge_policy,
    evaluate_thread_operation,
    merge_thread_bridge_policy,
)


class ThreadBridgePolicyTests(unittest.TestCase):
    def test_default_policy_is_off(self) -> None:
        decision = evaluate_thread_operation(build_default_thread_bridge_policy(), "read", capability_support="supported")

        self.assertEqual(decision["status"], "UNAVAILABLE")
        self.assertIn("thread-bridge-disabled", {item["code"] for item in decision["blockers"]})

    def test_read_only_policy_allows_read_but_blocks_send(self) -> None:
        policy = build_default_thread_bridge_policy()
        policy["mode"] = "read-only"
        policy["operations"]["read"]["enabled"] = True

        read = evaluate_thread_operation(
            policy,
            "read",
            target_scope="explicit-target",
            capability_support="supported",
        )
        send = evaluate_thread_operation(policy, "send", capability_support="supported")

        self.assertEqual(read["status"], "PASS")
        self.assertEqual(send["status"], "BLOCKED")

    def test_plan_policy_cannot_be_widened_by_profile(self) -> None:
        profile = build_default_thread_bridge_policy()
        profile["mode"] = "controlled"
        for operation in profile["operations"].values():
            operation["enabled"] = True
        plan = build_default_thread_bridge_policy()
        plan["mode"] = "read-only"
        plan["operations"]["read"]["enabled"] = True

        effective = merge_thread_bridge_policy(profile, plan)

        self.assertEqual(effective["mode"], "read-only")
        self.assertTrue(effective["operations"]["read"]["enabled"])
        self.assertFalse(effective["operations"]["send"]["enabled"])
        self.assertFalse(effective["operations"]["create"]["enabled"])

    def test_invalid_unbounded_policy_fails_closed(self) -> None:
        policy = build_default_thread_bridge_policy()
        policy["limits"]["maxImportedBytes"] = 100000

        with self.assertRaisesRegex(LifecycleError, "invalid"):
            merge_thread_bridge_policy(policy, None)


if __name__ == "__main__":
    unittest.main()
