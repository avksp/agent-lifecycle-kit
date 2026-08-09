from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.benchmarks.contracts import TASK_FAMILIES, load_suite, load_task

ROOT = Path(__file__).resolve().parents[2]


class ReferenceSuiteTests(unittest.TestCase):
    def test_manifest_contains_one_versioned_task_for_each_family(self) -> None:
        suite = load_suite(ROOT / "benchmarks/reference-tasks/manifest.json")
        tasks = suite.payload["tasks"]

        self.assertEqual(len(tasks), 5)
        self.assertEqual({item["family"] for item in tasks}, TASK_FAMILIES)
        for row in tasks:
            with self.subTest(task_id=row["id"]):
                loaded = load_task(suite, row["id"])
                self.assertEqual(loaded.oracle["taskVersion"], row["version"])
                self.assertEqual(len(loaded.task_digest), 64)
                self.assertEqual(len(loaded.oracle_digest), 64)


if __name__ == "__main__":
    unittest.main()
