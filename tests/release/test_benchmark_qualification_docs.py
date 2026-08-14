from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BenchmarkQualificationDocumentationTests(unittest.TestCase):
    PAGES = (
        ROOT / "docs/guides/model-harness-evaluation.md",
        ROOT / "docs/ru/guides/model-harness-evaluation.md",
        ROOT / "docs/reference/benchmark-qualification.md",
        ROOT / "docs/ru/reference/benchmark-qualification.md",
    )
    REQUIRED_FLOW = (
        "benchmark sample",
        "benchmark receipt-check",
        "benchmark qualify",
        "benchmark compare-routes",
        "agent-benchmark-run-receipt.v1",
        "NO_RECOMMENDATION",
    )

    def test_pages_exist_and_describe_the_same_public_flow(self) -> None:
        for page in self.PAGES:
            self.assertTrue(page.is_file(), page)
            content = page.read_text(encoding="utf-8")
            for marker in self.REQUIRED_FLOW:
                self.assertIn(marker, content, f"{marker}: {page}")

    def test_public_contract_pages_list_the_new_schema_ids(self) -> None:
        for relative_path in (
            "docs/reference/public-contracts.md",
            "docs/ru/reference/public-contracts.md",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            for marker in (
                "agent-benchmark-run-receipt.v1",
                "agent-benchmark-stratified-sample.v1",
                "agent-benchmark-qualification.v1",
                "agent-benchmark-route-comparison.v1",
            ):
                self.assertIn(marker, content, f"{marker}: {relative_path}")
