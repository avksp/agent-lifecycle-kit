from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.policy.quality_floor import quality_floor_mode, resolve_quality_floor  # noqa: E402


class QualityFloorTests(unittest.TestCase):
    def test_release_evidence_sets_release_floor(self) -> None:
        decision = resolve_quality_floor(
            task_shape="small-fix",
            baseline_profile=_baselines(),
            sdd_tier="S1",
            required_evidence=["release-proof"],
        )

        self.assertEqual(decision["status"], "PASS")
        self.assertEqual(decision["qualityFloor"], "release")
        self.assertIn("evidence-floor-release-proof-release", decision["reasonCodes"])

    def test_security_s2_sets_strict_floor(self) -> None:
        floor = quality_floor_mode(
            task_shape="feature",
            baseline_profile=_baselines(),
            sdd_tier="S2",
            risk_flags=["security"],
        )

        self.assertEqual(floor, "strict")

    def test_unknown_shape_fails_closed_with_standard_floor(self) -> None:
        decision = resolve_quality_floor(task_shape="unknown", baseline_profile=_baselines())

        self.assertEqual(decision["status"], "FAIL")
        self.assertEqual(decision["qualityFloor"], "standard")
        self.assertIn("quality-floor-task-shape-missing", {item["code"] for item in decision["blockers"]})


def _baselines() -> dict[str, object]:
    return json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
