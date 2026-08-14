from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.benchmarks import select_stratified_tasks, validate_stratified_sample


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"


class BenchmarkStratificationTests(unittest.TestCase):
    def test_same_seed_produces_same_sample_and_reports_shape(self) -> None:
        first = select_stratified_tasks(SUITE, seed="release-1-72", max_tasks=5, max_strata=16)
        second = select_stratified_tasks(SUITE, seed="release-1-72", max_tasks=5, max_strata=16)

        self.assertEqual(first, second)
        self.assertEqual(len(first["selectedTaskIds"]), 5)
        self.assertEqual({item["shape"] for item in first["strata"]}, {"planning", "review", "investigation", "implementation", "evidence"})
        self.assertEqual(validate_stratified_sample(first)["status"], "PASS")

    def test_bounds_report_omitted_tasks(self) -> None:
        sample = select_stratified_tasks(SUITE, seed="small", max_tasks=2, max_strata=2)

        self.assertEqual(len(sample["selectedTaskIds"]), 2)
        self.assertEqual(len(sample["omittedTaskIds"]), 3)
        self.assertLessEqual(len(sample["strata"]), 2)


if __name__ == "__main__":
    unittest.main()
