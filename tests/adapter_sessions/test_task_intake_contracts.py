from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.task_intake import start_adapter_task


class AdapterTaskIntakeContractTests(unittest.TestCase):
    def test_plain_text_returns_review_required_without_raw_text(self) -> None:
        raw = "Fix the failing checkout test"

        receipt = start_adapter_task(adapter_id="codex", task_text=raw)

        self.assertEqual(receipt["schemaVersion"], "agent-adapter-task-start-receipt.v1")
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["action"], "DRAFT_INTAKE")
        self.assertFalse(receipt["executionStarted"])
        self.assertFalse(receipt["lifecycleCoverageClaimed"])
        self.assertFalse(receipt["rawTaskTextStored"])
        self.assertTrue(receipt["requiresReview"])
        self.assertNotIn(raw, json.dumps(receipt, ensure_ascii=False))

    def test_source_selection_is_fail_closed(self) -> None:
        receipt = start_adapter_task(adapter_id="codex")

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["reviewBlockers"][0]["code"], "adapter-task-source-invalid")

    def test_secret_markers_block_planning_intake(self) -> None:
        marker = "BEGIN " + "OPENSSH PRIVATE KEY"
        receipt = start_adapter_task(adapter_id="codex", task_text=marker)

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["executionStarted"])
        self.assertIn("planning-import-secret-marker", {item["code"] for item in receipt["reviewBlockers"]})

    def test_candidate_out_writes_full_planning_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "candidate.json"

            receipt = start_adapter_task(adapter_id="codex", task_text="- Add adapter task intake", candidate_out=out)

            candidate = json.loads(out.read_text())
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(candidate["schemaVersion"], "agent-planning-import-result.v1")
        self.assertEqual(receipt["planningImport"]["importDigest"], candidate["importDigest"])


if __name__ == "__main__":
    unittest.main()
