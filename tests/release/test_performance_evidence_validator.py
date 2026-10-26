"""Tests for performance evidence validation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.performance_limits import performance_limits_to_json
from tools.performance.run_performance_baseline import collect_baseline
from tools.release.validate_performance_evidence import (
    compare_performance_baselines,
    validate_performance_evidence,
)


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
    def test_direct_script_entry_resolves_checkout_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy, baseline = root / "policy.json", root / "baseline.json"
            policy.write_text(json.dumps(_policy()), encoding="utf-8")
            collect_baseline(
                policy_path=policy,
                repository_root=Path.cwd(),
                output_path=baseline,
            )
            env = dict(os.environ, PYTHONPATH=str(Path.cwd() / "src"))
            env.pop("PYTHONHOME", None)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "tools/release/validate_performance_evidence.py",
                    "--policy",
                    str(policy),
                    "--input",
                    str(baseline),
                    "--evidence",
                    str(root / "validation.json"),
                ],
                env=env,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            report = json.loads((root / "validation.json").read_bytes())
            self.assertEqual(report["status"], "PASS")

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
            self.assertTrue(
                any(item["code"] == "performance-sample-operation-set-invalid" for item in result["blockers"])
            )

    def test_self_comparison_and_source_workload_metric_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy, baseline = root / "policy.json", root / "baseline.json"
            policy.write_text(json.dumps(_policy()), encoding="utf-8")
            original = collect_baseline(
                policy_path=policy,
                repository_root=Path.cwd(),
                output_path=baseline,
            )
            result = compare_performance_baselines(
                policy_path=policy,
                baseline_path=baseline,
                candidate_path=baseline,
                repository_root=Path.cwd(),
            )
            self.assertEqual(result["status"], "COMPARABLE")
            self.assertTrue(result["selfComparison"])
            self.assertEqual(result["operations"][0]["wallMedianRatio"], 1.0)
            for field in ("source", "workload", "metric", "environment", "summary"):
                with self.subTest(field=field):
                    value = json.loads(json.dumps(original))
                    if field == "source":
                        value["sourceInputs"]["digest"] = "a" * 64
                    elif field == "workload":
                        value["operations"][0]["workload"] = {"changed": True}
                    elif field == "metric":
                        value["metricDefinitions"]["p95"] = "unqualified"
                    elif field == "environment":
                        value["environment"]["python"] = "different"
                    else:
                        value["operations"][0]["summary"]["medianWallSeconds"] += 1
                    value["baselineDigest"] = canonical_digest(
                        {key: item for key, item in value.items() if key != "baselineDigest"}
                    )
                    changed = root / (field + ".json")
                    changed.write_text(json.dumps(value), encoding="utf-8")
                    result = compare_performance_baselines(
                        policy_path=policy,
                        baseline_path=baseline,
                        candidate_path=changed,
                        repository_root=Path.cwd(),
                    )
                    self.assertEqual(result["status"], "NO_RECOMMENDATION")
                    self.assertEqual(result["operations"], [])


if __name__ == "__main__":
    unittest.main()
