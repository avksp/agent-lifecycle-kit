"""Real public-API fixtures and fail-closed worker boundaries."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from agent_lifecycle.accounting.journal import Journal
from tools.performance.lifecycle_cases import (
    CASE_SIZES,
    _accounting_fixture,
    run_case,
)


class LifecycleCaseTests(unittest.TestCase):
    def test_four_real_fixtures_are_read_only_and_separate_timing(self) -> None:
        for operation, size in CASE_SIZES.items():
            with self.subTest(operation=operation):
                result = run_case(operation, source_root=Path.cwd())
                self.assertEqual(result["status"], "PASS")
                self.assertTrue(result["fixtureArtifactsUnchanged"])
                self.assertEqual(result["workload"]["size"], size)
                timings = [
                    result[key]
                    for key in (
                        "setupWallSeconds",
                        "operationWallSeconds",
                        "validationWallSeconds",
                    )
                ]
                self.assertTrue(all(value >= 0 for value in timings))
                self.assertGreaterEqual(result["workerWallSeconds"], sum(timings))
                self.assertIsNone(result["providerTokens"])
                self.assertIsNone(result["syscallCount"])
                if operation.startswith("accounting-"):
                    self.assertEqual(result["workload"]["events"], size + 1)
                else:
                    self.assertEqual(result["workload"]["tasks"], size)
                    self.assertEqual(result["workload"]["phase"], "AWAITING_AUTHORIZATION")

    def test_accounting_read_refuses_changed_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            read, _ = _accounting_fixture(Path(temporary), 1, stack)
            with mock.patch.object(Journal, "events", return_value=[]):
                with self.assertRaisesRegex(ValueError, "history changed"):
                    read()

    def test_unknown_operation_and_rebound_source_refuse(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown"):
            run_case("unknown", source_root=Path.cwd())
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "source root"):
                run_case("workflow-status-small", source_root=Path(temporary))


if __name__ == "__main__":
    unittest.main()
