"""Tests for performance evidence validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.performance_limits import performance_limits_to_json
from tools.performance.run_performance_baseline import collect_baseline
from tools.release.validate_performance_evidence import validate_performance_evidence


def _policy() -> dict:
    return {
        "schemaVersion": "agent-performance-budgets.v1",
        "revision": 1,
        "sourceRevision": "dbf0ffbc6a3f8bd53f7408f58cb4475d3aef2350",
        "limits": performance_limits_to_json(),
        "benchmark": {
            "warmupSamples": 0,
            "samplesPerCase": 1,
            "maxCommandWallSeconds": 5,
            "maxTotalWallSeconds": 20,
            "maxOutputBytes": 4096,
        },
        "operations": ["canonical-digest"],
        "productionPromotionClaimed": False,
    }


class PerformanceEvidenceValidatorTests(unittest.TestCase):
    def test_valid_baseline_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            baseline = root / "baseline.json"
            policy.write_text(json.dumps(_policy()), encoding="utf-8")
            collect_baseline(policy_path=policy, repository_root=Path.cwd(), output_path=baseline)
            result = validate_performance_evidence(policy_path=policy, input_path=baseline, repository_root=Path.cwd())
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["blockers"], [])

    def test_missing_sample_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            baseline = root / "baseline.json"
            policy.write_text(json.dumps(_policy()), encoding="utf-8")
            baseline.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-performance-baseline.v1",
                        "status": "PASS",
                        "sourceRevision": "dbf0ffbc6a3f8bd53f7408f58cb4475d3aef2350",
                        "environment": {"platform": "test", "python": "3.12", "implementation": "CPython"},
                        "comparability": {"status": "COMPARABLE"},
                        "operations": [],
                        "productionPromotionClaimed": False,
                    }
                ),
                encoding="utf-8",
            )
            result = validate_performance_evidence(policy_path=policy, input_path=baseline, repository_root=Path.cwd())
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any(item["code"] == "performance-sample-operation-set-invalid" for item in result["blockers"]))


if __name__ == "__main__":
    unittest.main()
