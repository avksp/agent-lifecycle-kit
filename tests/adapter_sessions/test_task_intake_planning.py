from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.task_intake import start_adapter_task


class AdapterTaskIntakePlanningTests(unittest.TestCase):
    def test_markdown_file_becomes_review_gated_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "task.md"
            task.write_text("# Feature\n\n- Add a small command entrypoint\n", encoding="utf-8")

            receipt = start_adapter_task(adapter_id="codex", task_file=task)

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["input"]["label"], "task.md")
        self.assertEqual(receipt["planningImport"]["candidateLifecycleStatus"], "DRAFT_REQUIRES_REVIEW")
        self.assertTrue(receipt["freezeBlocked"])

    def test_draft_plan_file_is_not_executable_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.manifest.json"
            plan.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-plan-manifest.v1",
                        "status": "DRAFT",
                        "package": {"title": "Draft"},
                        "specification": {"requirements": [{"description": "Review before execution"}]},
                    }
                ),
                encoding="utf-8",
            )

            receipt = start_adapter_task(adapter_id="codex", task_file=plan)

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertFalse(receipt["executionStarted"])
        self.assertFalse(receipt["lifecycleCoverageClaimed"])


if __name__ == "__main__":
    unittest.main()
