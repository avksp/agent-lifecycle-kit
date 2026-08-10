from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_qualified_planning_launch_profiles",
    ROOT / "tools/release/validate_qualified_planning_launch_profiles.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QualifiedPlanningLaunchProfileValidatorTests(unittest.TestCase):
    def test_repository_profiles_are_truthful(self) -> None:
        report = MODULE.validate_profiles(ROOT / "adapters", repository_root=ROOT)
        self.assertEqual(report["status"], "PASS")
        rows = {row["adapterId"]: row for row in report["profiles"]}
        self.assertEqual(rows["codex"]["profileStatus"], "CANDIDATE")
        self.assertEqual(rows["claude"]["profileStatus"], "CANDIDATE")
        self.assertEqual(rows["opencode"]["profileStatus"], "UNSUPPORTED")
        self.assertTrue(all(row["planningSupportStatus"] == "PLANNING_ONLY_UNSUPPORTED" for row in rows.values()))


if __name__ == "__main__":
    unittest.main()
