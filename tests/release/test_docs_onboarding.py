from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


class DocumentationOnboardingTests(unittest.TestCase):
    def test_onboarding_pages_exist_in_both_locales(self) -> None:
        pairs = (
            ("docs/guides/install-and-first-run.md", "docs/ru/guides/install-and-first-run.md"),
            ("docs/guides/commands-by-task.md", "docs/ru/guides/commands-by-task.md"),
            ("docs/guides/quickstart.md", "docs/ru/quickstart.md"),
        )
        for english, russian in pairs:
            with self.subTest(english=english, russian=russian):
                self.assertTrue((ROOT / english).is_file())
                self.assertTrue((ROOT / russian).is_file())

    def test_first_run_contract_is_copyable(self) -> None:
        english = (ROOT / "docs/guides/install-and-first-run.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/guides/install-and-first-run.md").read_text(encoding="utf-8")
        for text in (english, russian):
            for command in (
                "git clone https://github.com/avksp/agent-lifecycle-kit.git",
                "python3 -m venv .venv",
                "python -m pip install -e .",
                "python -m agent_lifecycle version",
                "agent-lifecycle version",
                "agent-lifecycle diagnose --no-install-plans",
                "agent-lifecycle start",
                "agent-workflow-orchestrator",
                ".venv/bin/agent-lifecycle version",
                ".venv\\Scripts\\agent-lifecycle.exe version",
            ):
                self.assertIn(command, text)
            for host_marker in ("codex plugin", "claude plugin", "OpenCode"):
                self.assertIn(host_marker, text)
            self.assertIn("command not found", text)
            self.assertIn("No module named agent_lifecycle", text)
            self.assertIn(TARGET_VERSION, text)

    def test_quickstart_routes_to_advanced_pages(self) -> None:
        english = (ROOT / "docs/guides/quickstart.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/quickstart.md").read_text(encoding="utf-8")
        for text in (english, russian):
            self.assertLessEqual(len(text.splitlines()), 150)
            self.assertIn("commands-by-task.md", text)
            self.assertIn("install-and-first-run.md", text)
            self.assertIn("agent-workflow-orchestrator", text)
            self.assertIn("reviewer-a", text)
            self.assertIn("reviewer-b", text)

    def test_architecture_explains_authority_and_guarantees(self) -> None:
        english = (ROOT / "docs/architecture/system-architecture.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/architecture/system-architecture.md").read_text(encoding="utf-8")
        for text, headings in (
            (english, ("Responsibility model", "How the guarantee chain is formed", "The guarantee boundary")),
            (russian, ("Распределение ответственности", "Как формируется цепочка гарантий", "Граница гарантий")),
        ):
            for heading in headings:
                self.assertIn(heading, text)
            self.assertIn("PASS", text)
            self.assertIn("REVIEW_REQUIRED", text)
            self.assertIn("BLOCKED", text)

    def test_public_package_pin_is_consistent(self) -> None:
        paths = (
            ROOT / "README.md",
            ROOT / "docs/README.md",
            ROOT / "docs/ru/README.md",
            ROOT / "docs/guides/install-and-first-run.md",
            ROOT / "docs/ru/guides/install-and-first-run.md",
        )
        pins = set()
        for path in paths:
            text = path.read_text(encoding="utf-8")
            pins.update(re.findall(r"agent-lifecycle-kit==([0-9]+\.[0-9]+\.[0-9]+)", text))
        self.assertEqual(pins, {TARGET_VERSION})


if __name__ == "__main__":
    unittest.main()
