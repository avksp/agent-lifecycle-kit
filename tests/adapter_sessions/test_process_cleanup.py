from __future__ import annotations

import os
import sys
import unittest

from agent_lifecycle.adapter_sessions.process import run_process


class ProcessCleanupTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "process-group fixture uses POSIX sessions")
    def test_timeout_terminates_descendant_group(self) -> None:
        script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(30)"

        result = run_process(
            [sys.executable, "-c", script],
            env=dict(os.environ),
            timeout_seconds=0.1,
            cleanup_grace_seconds=0.5,
            operation_id="cleanup-op",
            attempt_id="cleanup-attempt",
            adapter_id="fixture",
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["timedOut"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["blockers"][0]["code"], "adapter-process-timeout")

    def test_normal_exit_has_cleanup_receipt(self) -> None:
        result = run_process(
            [sys.executable, "-c", "pass"],
            env=dict(os.environ),
            timeout_seconds=5,
            operation_id="normal-op",
            attempt_id="normal-attempt",
            adapter_id="fixture",
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["processReceipt"]["cleanup"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
