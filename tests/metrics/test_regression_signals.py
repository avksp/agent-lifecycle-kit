from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics import summarize_regression_signals  # noqa: E402


class RegressionSignalTests(unittest.TestCase):
    def test_empty_regression_signals_pass(self) -> None:
        summary = summarize_regression_signals([])

        self.assertEqual(summary["schemaVersion"], "agent-lifecycle-regression-signals.v1")
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["signalCount"], 0)

    def test_blocking_signal_blocks_tuning(self) -> None:
        summary = summarize_regression_signals([{"type": "failedFinalAudit", "count": 1, "severity": "HIGH"}])

        self.assertEqual(summary["status"], "BLOCK")
        self.assertEqual(summary["blockingSignals"][0]["type"], "failedFinalAudit")

    def test_invalid_signal_fails_closed(self) -> None:
        summary = summarize_regression_signals([{"type": "rollback", "count": -1}])

        self.assertEqual(summary["status"], "FAIL")
        self.assertIn("regression-signal-count", {item["code"] for item in summary["blockers"]})


if __name__ == "__main__":
    unittest.main()
