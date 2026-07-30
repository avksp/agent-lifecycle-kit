from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402


class CliContractMetricsCommandTests(unittest.TestCase):
    def test_contract_policy_and_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "policy.json"

            code, policy = _run_cli(["contract", "policy", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(policy["schemaVersion"], "agent-public-contract-policy.v1")
            self.assertTrue(out.is_file())

            code, validation = _run_cli(["contract", "check", "--policy", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(validation["schemaVersion"], "agent-public-contract-policy-validation.v1")
            self.assertEqual(validation["status"], "PASS")

    def test_contract_check_cli_fails_closed_on_invalid_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-public-contract-policy.v1",
                        "status": "PASS",
                        "rules": {},
                        "requiredCoreSchemas": [],
                        "schemas": [],
                        "cliOutputs": [],
                        "productionPromotionClaimed": False,
                        "policyDigest": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

            code, payload = _run_cli(["contract", "check", "--policy", str(policy)])

        self.assertEqual(code, 2)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(payload["code"], "contract-policy-validation-failed")

    def test_metrics_cost_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "cost.json"
            report.write_text(json.dumps(_cost_report()), encoding="utf-8")

            code, payload = _run_cli(["metrics", "cost-check", "--receipt", str(report)])

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-cost-validation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertLessEqual(payload["ratios"]["pipelineTokenShare"], payload["limits"]["maxPipelineTokenShare"])


def _cost_report() -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-cost-report.v1",
        "mode": "standard",
        "entries": [
            {"category": "implementation", "tokens": 8000, "steps": 5},
            {"category": "productValidation", "tokens": 3000, "steps": 3},
            {"category": "pipelineCompliance", "tokens": 2200, "steps": 3},
            {"category": "coordination", "tokens": 600, "steps": 1},
        ],
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    unittest.main()
