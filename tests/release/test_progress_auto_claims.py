from __future__ import annotations

import unittest

from agent_lifecycle.reporting.progress_hooks import build_progress_hook_policy


class ProgressAutoClaimReleaseTests(unittest.TestCase):
    def test_policy_keeps_plugin_install_separate_from_lifecycle_proof(self) -> None:
        policy = build_progress_hook_policy(hook_mode="stderr")

        self.assertFalse(policy["defaultEnabled"])
        self.assertFalse(policy["pluginInstalledIsLifecycleProof"])
        self.assertTrue(policy["autoClaimRequiresManagedWorkflowProof"])
        self.assertTrue(policy["stdoutJsonPreserved"])
        self.assertFalse(policy["modelCallsStarted"])


if __name__ == "__main__":
    unittest.main()
