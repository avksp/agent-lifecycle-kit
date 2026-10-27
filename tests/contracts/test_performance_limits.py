"""Tests for the closed performance-limit contract."""

from __future__ import annotations

import unittest
import json
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.performance_limits import (
    DEFAULT_PERFORMANCE_LIMITS,
    performance_limits_from_json,
    performance_limits_to_json,
    validate_performance_policy,
)


class PerformanceLimitContractTests(unittest.TestCase):
    def test_default_limits_round_trip_through_json(self) -> None:
        encoded = performance_limits_to_json()
        self.assertEqual(performance_limits_from_json(encoded), DEFAULT_PERFORMANCE_LIMITS)

    def test_unknown_limit_is_rejected(self) -> None:
        encoded = performance_limits_to_json()
        encoded["unknown"] = 1
        with self.assertRaises(LifecycleError) as raised:
            performance_limits_from_json(encoded)
        self.assertEqual(raised.exception.code, "performance-limits-fields-invalid")

    def test_invalid_ratio_is_rejected(self) -> None:
        encoded = performance_limits_to_json()
        encoded["maxEd25519OptimizedToReferenceMedianRatioBps"] = 10_001
        with self.assertRaises(LifecycleError) as raised:
            performance_limits_from_json(encoded)
        self.assertEqual(raised.exception.code, "performance-limit-ratio-invalid")

    def test_benchmark_cannot_raise_sampling_time_or_output_caps(self) -> None:
        path = Path(__file__).resolve().parents[2] / "policy/performance-budgets.json"
        for field, excess in (
            ("warmupSamples", 3),
            ("samplesPerCase", 8),
            ("maxCommandWallSeconds", 121),
            ("maxTotalWallSeconds", 601),
            ("maxOutputBytes", 16 * 1024 * 1024 + 1),
        ):
            with self.subTest(field=field):
                policy = json.loads(path.read_bytes())
                policy["benchmark"][field] = excess
                with self.assertRaises(LifecycleError):
                    validate_performance_policy(policy)

    def test_policy_cannot_expand_the_typed_sample_limit(self) -> None:
        path = Path(__file__).resolve().parents[2] / "policy/performance-budgets.json"
        policy = json.loads(path.read_bytes())
        policy["limits"]["maxBenchmarkSamplesPerCase"] = 31
        with self.assertRaises(LifecycleError):
            validate_performance_policy(policy)


if __name__ == "__main__":
    unittest.main()
