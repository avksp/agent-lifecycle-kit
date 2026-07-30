from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics import validate_lifecycle_baselines  # noqa: E402


class LifecycleBaselineTests(unittest.TestCase):
    def test_repository_baseline_profile_is_valid_and_provider_neutral(self) -> None:
        profile = json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))

        validation = validate_lifecycle_baselines(profile)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["taskShapeCount"], 6)
        self.assertEqual(profile["taskShapes"]["adapter"]["minMode"], "strict")
        self.assertEqual(profile["riskFloors"]["S2"], "strict")
        self.assertFalse(profile["productionPromotionClaimed"])

    def test_baseline_profile_rejects_default_below_quality_floor(self) -> None:
        profile = json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))
        profile["taskShapes"]["adapter"]["defaultMode"] = "standard"

        validation = validate_lifecycle_baselines(profile)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("baseline-shape-default-below-min", {item["code"] for item in validation["blockers"]})

    def test_baseline_profile_rejects_invalid_global_thresholds(self) -> None:
        profile = json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))
        profile["minimumReportsForConfidence"] = 0
        profile["modeOrder"] = ["standard", "light"]
        profile["riskFloors"]["security"] = "cheap"

        validation = validate_lifecycle_baselines(profile)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("baseline-minimum-reports", codes)
        self.assertIn("baseline-mode-order", codes)
        self.assertIn("baseline-risk-floor-mode", codes)


if __name__ == "__main__":
    unittest.main()
