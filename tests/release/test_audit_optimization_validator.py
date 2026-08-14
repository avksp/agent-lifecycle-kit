from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_audit_optimization import validate_audit_optimization, _check_path


class AuditOptimizationValidatorTests(unittest.TestCase):
    def test_current_optimizer_boundary_passes(self) -> None:
        result = validate_audit_optimization(Path("work/release-1-70"))

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["modelCallsStarted"])
        self.assertFalse(result["hostExecutionStarted"])

    def test_host_process_and_sensitive_storage_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.py"
            path.write_text("import subprocess\nrawPromptStored = True\nsubprocess.run(['host'])\n", encoding="utf-8")

            result = _check_path(path)

        codes = {item["code"] for item in result["blockers"]}
        self.assertIn("optimizer-boundary-import", codes)
        self.assertIn("optimizer-sensitive-storage-marker", codes)
        self.assertIn("optimizer-host-process-call", codes)


if __name__ == "__main__":
    unittest.main()
