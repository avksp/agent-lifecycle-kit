from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_risk_policy_boundary import validate_boundary

ROOT = Path(__file__).resolve().parents[2]


class RiskPolicyBoundaryValidatorTests(unittest.TestCase):
    def test_repository_policy_passes(self) -> None:
        result = validate_boundary(
            ROOT / "src/agent_lifecycle/policy/risk_execution.py",
            ROOT / "src/agent_lifecycle/policy/quality_floor.py",
            ROOT / "src/agent_lifecycle/policy/adaptive_lifecycle.py",
        )
        self.assertEqual(result["status"], "PASS")

    def test_adaptive_policy_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "risk.py"
            path.write_text(
                "from agent_lifecycle.policy.quality_floor import resolve_quality_floor\n"
                "from agent_lifecycle.model_routing import resolve_model_route\n"
                "from agent_lifecycle.policy.adaptive_lifecycle import build_adaptive_lifecycle_decision\n",
                encoding="utf-8",
            )
            result = validate_boundary(
                path,
                ROOT / "src/agent_lifecycle/policy/quality_floor.py",
                ROOT / "src/agent_lifecycle/policy/adaptive_lifecycle.py",
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("risk-policy-adaptive-authority-imported", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
