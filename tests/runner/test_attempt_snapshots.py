from __future__ import annotations

import importlib
import unittest


class RemovedRunnerAttemptSnapshotTests(unittest.TestCase):
    def test_attempt_snapshot_module_is_not_an_active_execution_surface(self) -> None:
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("agent_lifecycle.runner.attempt_snapshots")


if __name__ == "__main__":
    unittest.main()
