from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGLISH = ROOT / "docs/reference/performance-and-resource-budgets.md"
RUSSIAN = ROOT / "docs/ru/reference/performance-and-resource-budgets.md"


class PerformanceDocumentationTests(unittest.TestCase):
    def test_bilingual_pages_exist_and_cover_the_same_contract(self) -> None:
        english = ENGLISH.read_text(encoding="utf-8")
        russian = RUSSIAN.read_text(encoding="utf-8")
        for text in (english, russian):
            self.assertIn("Ed25519", text)
            self.assertIn("tracked-release", text)
            self.assertIn("full-repository", text)
            self.assertIn("NO_RECOMMENDATION", text)
            self.assertIn("INCOMPLETE", text)
            self.assertIn("BLOCKED", text)
            self.assertIn("policy/performance-budgets.json", text)
            self.assertIn("performance_limits.py", text)
            self.assertIn("shell=True", text)
        for marker in ("20%", "128", "16", "256", "600", "96"):
            self.assertIn(marker, english)
            self.assertIn(marker, russian)

    def test_current_operations_and_comparison_boundaries_remain_documented(self) -> None:
        for path in (ENGLISH, RUSSIAN):
            text = path.read_text(encoding="utf-8")
            for marker in (
                "workflow-status-small", "workflow-status-growing",
                "accounting-read-small", "accounting-read-growing",
                "validate_performance_evidence.py", "run_performance_baseline.py",
                "--compare-input", "--repository-root", "--policy", "--evidence",
                "wallSeconds", "PYTHONPATH", "PYTHONHOME", "null", "p50", "p95",
            ):
                self.assertIn(marker, text, (path, marker))

    def test_operating_headings_are_topic_based_and_history_remains_reachable(self) -> None:
        for path in (ENGLISH, RUSSIAN):
            text = path.read_text(encoding="utf-8")
            headings = re.findall(r"^#{1,6} .+$", text, re.MULTILINE)
            self.assertTrue(headings)
            for heading in headings:
                self.assertNotRegex(heading, r"(?i)(?:release|релиз)\s+\d+\.\d+")
            target = (
                "https://github.com/avksp/agent-lifecycle-kit/blob/v2.41.0/CHANGELOG.md"
                if path == RUSSIAN else "../../CHANGELOG.md"
            )
            self.assertIn(target, text)
            self.assertTrue((ROOT / "CHANGELOG.md").is_file())

    def test_pages_explicitly_reject_constant_time_claims_and_caching(self) -> None:
        for path in (ENGLISH, RUSSIAN):
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("constant-time" if path == ENGLISH else "постоянном времени", text)
            self.assertIn("cach" if path == ENGLISH else "кэширован", text)


if __name__ == "__main__":
    unittest.main()
