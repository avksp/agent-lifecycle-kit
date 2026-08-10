from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_planning_launch_boundary",
    ROOT / "tools/release/validate_planning_launch_boundary.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PlanningLaunchBoundaryValidatorTests(unittest.TestCase):
    def test_repository_boundary_passes(self) -> None:
        report = MODULE.validate_boundary(
            {
                "start": ROOT / "src/agent_lifecycle/adapter_sessions/launcher.py",
                "planning-launch": ROOT / "src/agent_lifecycle/adapter_sessions/planning_launch.py",
                "launcher": ROOT / "src/agent_lifecycle/adapter_sessions/launcher.py",
                "process": ROOT / "src/agent_lifecycle/adapter_sessions/process.py",
            }
        )
        self.assertEqual(report["status"], "PASS")

    def test_missing_marker_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.py"
            path.write_text("value = 1\n", encoding="utf-8")
            report = MODULE.validate_boundary({role: path for role in MODULE.REQUIRED_MARKERS})
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("planning-boundary-marker-missing", {item["code"] for item in report["blockers"]})


if __name__ == "__main__":
    unittest.main()
