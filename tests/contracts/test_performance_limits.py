"""Tests for the closed performance-limit contract."""

from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.performance_limits import (
    DEFAULT_PERFORMANCE_LIMITS,
    performance_limits_from_json,
    performance_limits_to_json,
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


if __name__ == "__main__":
    unittest.main()
