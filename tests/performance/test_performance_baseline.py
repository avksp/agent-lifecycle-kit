"""Tests for bounded baseline collection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.performance_limits import performance_limits_to_json
from tools.performance.run_performance_baseline import collect_baseline


def _policy() -> dict:
    return {
        "schemaVersion": "agent-performance-budgets.v1",
        "revision": 1,
        "sourceRevision": "dbf0ffbc6a3f8bd53f7408f58cb4475d3aef2350",
        "limits": performance_limits_to_json(),
        "benchmark": {
            "warmupSamples": 1,
            "samplesPerCase": 1,
            "maxCommandWallSeconds": 5,
            "maxTotalWallSeconds": 20,
            "maxOutputBytes": 4096,
        },
        "operations": ["canonical-digest"],
        "productionPromotionClaimed": False,
    }


class PerformanceBaselineTests(unittest.TestCase):
    def test_in_process_baseline_is_bounded_and_revision_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            output = root / "evidence" / "baseline.json"
            policy.write_text(json.dumps(_policy()), encoding="utf-8")
            result = collect_baseline(policy_path=policy, repository_root=Path.cwd(), output_path=output)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["comparability"]["status"], "COMPARABLE")
            self.assertEqual(result["operations"][0]["summary"]["sampleCount"], 1)
            self.assertTrue(output.is_file())
            self.assertEqual(result["productionPromotionClaimed"], False)


if __name__ == "__main__":
    unittest.main()
