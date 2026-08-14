from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from tools.release.validate_process_boundary import validate_process_boundary


ROOT = Path(__file__).resolve().parents[2]


class ProcessBoundaryValidatorTests(unittest.TestCase):
    def test_current_process_boundary_passes(self) -> None:
        result = validate_process_boundary(
            [
                ROOT / "src/agent_lifecycle/adapter_sessions/process.py",
                ROOT / "src/agent_lifecycle/adapter_sessions/process_groups.py",
            ]
        )

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["shellExecutionAllowed"])

    def test_shell_true_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "process.py"
            path.write_text("import subprocess\nsubprocess.Popen(['unsafe'], shell=True)\n", encoding="utf-8")
            result = validate_process_boundary([path, ROOT / "src/agent_lifecycle/adapter_sessions/process_groups.py"])

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("process-boundary-shell-enabled", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
