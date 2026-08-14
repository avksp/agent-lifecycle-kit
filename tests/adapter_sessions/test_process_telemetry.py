from __future__ import annotations

import os
import unittest

from agent_lifecycle.adapter_sessions.process_telemetry import ProcessTelemetry, capture_process_snapshot


class ProcessTelemetryTests(unittest.TestCase):
    def test_unavailable_process_is_explicit(self) -> None:
        telemetry = ProcessTelemetry(pid=None)

        result = telemetry.finish()

        self.assertEqual(result["cpuMs"]["availability"], "UNAVAILABLE")
        self.assertEqual(result["peakMemoryMb"]["availability"], "UNAVAILABLE")
        self.assertEqual(result["processCount"]["availability"], "UNAVAILABLE")
        self.assertGreaterEqual(result["elapsedMs"], 0)

    def test_current_process_snapshot_is_local_only(self) -> None:
        snapshot = capture_process_snapshot(os.getpid())

        self.assertIsInstance(snapshot, dict)
        self.assertNotIn("argv", snapshot)
        self.assertNotIn("environment", snapshot)


if __name__ == "__main__":
    unittest.main()
