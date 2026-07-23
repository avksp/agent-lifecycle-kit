from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "skills"

EXPECTED_SKILLS = {
    "agent-first-planning",
    "audit-agent-plan",
    "agent-plan-to-workers",
    "agent-workflow-orchestrator",
    "audit-plan-implementation",
}

PROJECT_MARKERS = (
    "board" + "-app",
    "board" + "2.0",
    "Dot" + "Space",
    "/Vol" + "umes/",
    "/Us" + "ers/",
)


class SkillPackTests(unittest.TestCase):
    def skill_files(self) -> dict[str, Path]:
        self.assertTrue(SKILLS_ROOT.is_dir())
        return {
            path.parent.name: path
            for path in sorted(SKILLS_ROOT.glob("*/SKILL.md"))
        }

    def test_exact_canonical_skill_set(self) -> None:
        self.assertEqual(set(self.skill_files()), EXPECTED_SKILLS)

    def test_skills_are_thin_and_stage_routed(self) -> None:
        for name, path in self.skill_files().items():
            data = path.read_bytes()
            text = data.decode("utf-8").replace("\r\n", "\n")

            with self.subTest(skill=name):
                self.assertLessEqual(len(data), 8192)
                self.assertTrue(text.startswith("---\n"))
                self.assertIn(f"name: {name}\n", text)
                self.assertIn("description:", text)
                self.assertRegex(
                    text,
                    re.compile(r"^## (Contract|Inputs|Lifecycle)", re.MULTILINE),
                )

    def test_skills_are_project_neutral(self) -> None:
        for name, path in self.skill_files().items():
            text = path.read_text(encoding="utf-8")
            with self.subTest(skill=name):
                for marker in PROJECT_MARKERS:
                    self.assertNotIn(marker, text)

    def test_pipeline_roles_are_present(self) -> None:
        joined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in self.skill_files().values()
        )
        for marker in EXPECTED_SKILLS:
            with self.subTest(role=marker):
                self.assertIn(marker, joined)


if __name__ == "__main__":
    unittest.main()
