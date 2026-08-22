from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


class PlanIntegrityDocumentationTests(unittest.TestCase):
    def test_english_and_russian_plan_verification_pages_cover_same_contract(self) -> None:
        english = (ROOT / "docs/reference/plan-verification.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/plan-verification.md").read_text(encoding="utf-8")

        for text in (english, russian):
            self.assertIn("agent-lifecycle plan verify", text)
            self.assertIn("agent-plan-verification-receipt.v1", text)
            self.assertIn("agent-plan-manifest.v1", text)
            self.assertIn("agent-plan-lock.v2", text)
            self.assertIn("validation.commands", text)
            self.assertIn("S2", text)
            self.assertIn("implementation", text)
            self.assertIn("tasks/release-1-79/plan.manifest.json", text)
            self.assertIn("tasks/release-1-79/plan.lock.json", text)

    def test_release_docs_link_plan_verification_and_use_current_version(self) -> None:
        expected_pin = f"agent-lifecycle-kit=={TARGET_VERSION}"
        expected_ref = f"v{TARGET_VERSION}"
        paths = (
            "README.md",
            "docs/README.md",
            "docs/ru/README.md",
            "docs/guides/install-and-first-run.md",
            "docs/ru/guides/install-and-first-run.md",
            "docs/reference/cli.md",
            "docs/ru/reference/cli.md",
            "docs/guides/code-review-workflows.md",
            "docs/ru/guides/code-review-workflows.md",
            "docs/reference/managed-lifecycle-runner.md",
            "docs/ru/reference/managed-lifecycle-runner.md",
            "docs/architecture/system-architecture.md",
            "docs/ru/architecture/system-architecture.md",
        )
        for relative in paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("plan-verification", text, relative)
        for relative in (
            "docs/guides/install-and-first-run.md",
            "docs/ru/guides/install-and-first-run.md",
            "docs/reference/cli.md",
            "docs/ru/reference/cli.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(expected_pin, text, relative)
        self.assertIn(expected_ref, (ROOT / "docs/guides/install-and-first-run.md").read_text(encoding="utf-8"))
        self.assertIn(expected_ref, (ROOT / "docs/ru/guides/install-and-first-run.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
