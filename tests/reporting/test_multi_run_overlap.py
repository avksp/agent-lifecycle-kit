from __future__ import annotations

import unittest

from agent_lifecycle.reporting.attention import build_multi_run_overlap


class MultiRunOverlapTests(unittest.TestCase):
    def test_same_run_does_not_report_self_overlap(self) -> None:
        source = {
            "runId": "run-a",
            "status": "PASS",
            "summary": {"packageId": "p-a", "planRevision": 1},
            "ownershipPaths": ["src/a.py", "src/a.py"],
        }
        self.assertEqual(build_multi_run_overlap([source]), [])

    def test_overlap_order_is_independent_of_input_order(self) -> None:
        first = {
            "runId": "run-a",
            "status": "PASS",
            "summary": {"packageId": "p-a", "planRevision": 1},
            "ownershipPaths": ["src/a.py", "src/b.py"],
        }
        second = {
            "runId": "run-b",
            "status": "PASS",
            "summary": {"packageId": "p-b", "planRevision": 2},
            "ownershipPaths": ["src/b.py"],
        }
        self.assertEqual(build_multi_run_overlap([first, second]), build_multi_run_overlap([second, first]))


if __name__ == "__main__":
    unittest.main()
