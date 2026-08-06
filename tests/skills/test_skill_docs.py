from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SkillDocumentationTests(unittest.TestCase):
    def test_workflow_skill_points_to_cookbook_without_claiming_execution(self) -> None:
        text = (ROOT / "skills/agent-workflow-orchestrator/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("docs/guides/lifecycle-cookbook.md", text)
        self.assertIn("research-only", text)
        self.assertIn("Markdown plan review", text)
        self.assertIn("atomic commands", text)

    def test_audit_skills_link_cookbook_and_keep_review_boundaries(self) -> None:
        plan_audit = (ROOT / "skills/audit-agent-plan/SKILL.md").read_text(encoding="utf-8")
        implementation_audit = (ROOT / "skills/audit-plan-implementation/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("docs/guides/lifecycle-cookbook.md", plan_audit)
        self.assertIn("draft-only", plan_audit)
        self.assertIn("docs/guides/lifecycle-cookbook.md#audit-implementation-evidence", implementation_audit)
        self.assertIn("typed audit", implementation_audit)


if __name__ == "__main__":
    unittest.main()
