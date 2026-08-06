from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import write_json_create
from agent_lifecycle.context.external_memory import build_episode_retrieval_with_external_context, import_external_memory_context


class ExternalMemoryContextTests(unittest.TestCase):
    def test_external_memory_receipt_can_feed_episode_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "taskId": "T-1"}), encoding="utf-8")
            source = root / "memory.md"
            source.write_text("Prior memory: retry task needs idempotency evidence.", encoding="utf-8")
            receipt = import_external_memory_context(source, citation="operator memory export")
            receipt_path = root / "work/external-context.json"
            write_json_create(receipt_path, receipt)

            retrieval = build_episode_retrieval_with_external_context(
                root,
                ["evidence/result.json"],
                external_context_paths=[receipt_path],
                query="",
                target_tokens=2048,
            )

            self.assertEqual(retrieval["status"], "PASS")
            self.assertEqual(retrieval["resultCount"], 1)
            self.assertEqual(retrieval["externalContextHintCount"], 1)
            self.assertFalse(retrieval["externalContextHints"][0]["sourceOfTruth"])
            self.assertFalse(retrieval["externalContextHints"][0]["proof"])


if __name__ == "__main__":
    unittest.main()
