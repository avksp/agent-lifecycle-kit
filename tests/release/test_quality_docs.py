from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGLISH = ROOT / "docs/guides/contributing-and-quality.md"
RUSSIAN = ROOT / "docs/ru/guides/contributing-and-quality.md"


class QualityDocumentationTests(unittest.TestCase):
    def test_bilingual_quality_guides_exist_and_cover_the_same_contract(self) -> None:
        english = ENGLISH.read_text(encoding="utf-8")
        russian = RUSSIAN.read_text(encoding="utf-8")
        required = (
            "uv sync --locked --group quality",
            "ruff check src/agent_lifecycle",
            "ruff format --check src/agent_lifecycle",
            "mypy src/agent_lifecycle",
            "python3 -m unittest discover -s tests -t . -q",
            "run_python_quality.py",
            "validate_python_quality.py",
            "agent-lifecycle-error.v1",
            "importlib.resources",
            "76%",
            "python-api.md",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, english)
        for marker in (
            "uv sync --locked --group quality",
            "ruff check src/agent_lifecycle",
            "ruff format --check src/agent_lifecycle",
            "mypy src/agent_lifecycle",
            "python3 -m unittest discover -s tests -t . -q",
            "run_python_quality.py",
            "validate_python_quality.py",
            "agent-lifecycle-error.v1",
            "76%",
            "python-api.md",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, russian)

    def test_guides_preserve_bilingual_links(self) -> None:
        english = ENGLISH.read_text(encoding="utf-8")
        russian = RUSSIAN.read_text(encoding="utf-8")
        for path in ("../reference/cli-errors.md", "../reference/python-api.md"):
            with self.subTest(path=path):
                self.assertIn(path, english)
                self.assertIn(path, russian)


if __name__ == "__main__":
    unittest.main()
