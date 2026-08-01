from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.planning import (
    build_task_template_library,
    render_task_template,
    validate_task_template_library,
)

ROOT = Path(__file__).resolve().parents[2]


class TaskTemplateTests(unittest.TestCase):
    def test_builtin_templates_are_draft_only_and_review_gated(self) -> None:
        library = build_task_template_library()

        validation = validate_task_template_library(project_root=ROOT, library=library)

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(library["enabledByDefault"])
        self.assertTrue(library["draftOnly"])
        self.assertEqual({item["templateId"] for item in library["templates"]}, {
            "bugfix",
            "idea-to-pr",
            "pr-review",
            "merge-conflict-repair",
            "release-readiness",
        })
        self.assertTrue(all(item["freezeBlocked"] for item in library["templates"]))

    def test_bugfix_template_renders_without_runtime_defaults(self) -> None:
        rendered = render_task_template(
            "bugfix",
            project_root=ROOT,
            variables={
                "bug_summary": "profile endpoint returns 500",
                "failing_command": "python -m unittest tests.profile",
            },
        )

        self.assertEqual(rendered["status"], "PASS")
        self.assertTrue(rendered["draftOnly"])
        self.assertIn("bug-forensics", rendered["qualityProfiles"])
        self.assertIn("Template status: DRAFT-ONLY.", rendered["content"])
        self.assertNotIn("runtime-provider-placeholder", rendered["content"])
        self.assertNotIn("enabledByDefault: true", rendered["content"])

    def test_template_validation_rejects_default_activation_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "templates/tasks/bugfix.md"
            template.parent.mkdir(parents=True)
            template.write_text(
                "Template status: DRAFT-ONLY.\n"
                "Review gate: required.\n"
                "Freeze gate: required.\n"
                "Runtime defaults: none.\n"
                "Quality profile: bug-forensics optional\n"
                "enabledByDefault: true\n",
                encoding="utf-8",
            )

            validation = validate_task_template_library(project_root=root, template_id="bugfix")

            self.assertEqual(validation["status"], "FAIL")
            self.assertIn("task-template-forbidden-marker", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
