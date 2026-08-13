from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from tools.release.validate_thread_bridge_boundary import validate_thread_bridge_boundary


class ThreadBridgeBoundaryValidatorTests(unittest.TestCase):
    def test_current_thread_bridge_paths_pass(self) -> None:
        paths = [
            Path("src/agent_lifecycle/host_protocol/thread_bridge.py"),
            Path("src/agent_lifecycle/policy/thread_bridge.py"),
            Path("src/agent_lifecycle/cli/dispatch.py"),
            Path("src/agent_lifecycle/cli/dispatch_observability.py"),
        ]

        result = validate_thread_bridge_boundary(paths)

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["modelCallsStarted"])
        self.assertFalse(result["hostExecutionStarted"])

    def test_process_call_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.py"
            path.write_text("import subprocess\nsubprocess.run(['host'])\n", encoding="utf-8")

            result = validate_thread_bridge_boundary([path])

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("thread-boundary-process-call", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
