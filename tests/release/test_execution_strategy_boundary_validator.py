from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_execution_strategy_boundary import validate_boundary

ROOT = Path(__file__).resolve().parents[2]


class ExecutionStrategyBoundaryValidatorTests(unittest.TestCase):
    def test_repository_strategy_passes(self) -> None:
        result = validate_boundary(*_repository_paths())

        self.assertEqual(result["status"], "PASS")
        self.assertTrue(all(result["checks"].values()))

    def test_direct_host_launch_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.py"
            strategy.write_text(
                "from agent_lifecycle.policy.risk_execution import derive_risk_execution_profile\n"
                "from agent_lifecycle.policy.adaptive_lifecycle import build_adaptive_lifecycle_decision, small_model_packet_eligibility\n"
                "from agent_lifecycle.policy.quality_floor import mode_index\n"
                "from agent_lifecycle.review_mesh.recommendation import recommend_review_mesh_for_plan_manifest\n"
                "import subprocess\n",
                encoding="utf-8",
            )
            paths = list(_repository_paths())
            paths[0] = strategy
            result = validate_boundary(*paths)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "execution-strategy-host-or-provider-import",
            {item["code"] for item in result["blockers"]},
        )

    def test_inverse_policy_dependency_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inverse = Path(tmp) / "risk.py"
            inverse.write_text(
                "from agent_lifecycle.policy.execution_strategy import resolve_execution_strategy\n",
                encoding="utf-8",
            )
            paths = list(_repository_paths())
            paths[1] = inverse
            result = validate_boundary(*paths)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "execution-strategy-inverse-authority-import",
            {item["code"] for item in result["blockers"]},
        )


def _repository_paths() -> tuple[Path, Path, Path, Path, Path, Path]:
    return (
        ROOT / "src/agent_lifecycle/policy/execution_strategy.py",
        ROOT / "src/agent_lifecycle/policy/risk_execution.py",
        ROOT / "src/agent_lifecycle/policy/adaptive_lifecycle.py",
        ROOT / "src/agent_lifecycle/policy/quality_floor.py",
        ROOT / "src/agent_lifecycle/review_mesh/recommendation.py",
        ROOT / "src/agent_lifecycle/compiler/small_model_packets.py",
    )


if __name__ == "__main__":
    unittest.main()
