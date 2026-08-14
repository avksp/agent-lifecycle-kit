from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_benchmark_qualification import validate_release


ROOT = Path(__file__).resolve().parents[2]


class BenchmarkQualificationValidatorTests(unittest.TestCase):
    def test_release_boundary_is_offline_and_passes_bounded_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_release(root=Path(tmp), evidence_path=Path(tmp) / "qualification.json")

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["modelCallsStarted"])
        self.assertFalse(result["hostLaunchStarted"])
        self.assertEqual(result["sample"]["bounds"], {"maxTasks": 24, "maxStrata": 16})


if __name__ == "__main__":
    unittest.main()
