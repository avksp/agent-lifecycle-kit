from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics import build_usage_export, validate_usage_export  # noqa: E402


class UsageExportRedactionTests(unittest.TestCase):
    def test_budget_reason_redacts_local_paths_and_secret_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "usage.json"
            _write_json(
                artifact,
                {
                    "schemaVersion": "agent-host-operation-receipt.v1",
                    "host": "local-agent",
                    "runId": "run-1",
                    "taskId": "WS-01",
                    "operationId": "op",
                    "usage": {"inputTokens": 1, "outputTokens": 1},
                    "budgetDecision": {
                        "action": "pause",
                        "reason": "see " + "/Vol" + "umes/private/log and gh" + "p_example",
                    },
                },
            )

            export = build_usage_export(artifact_paths=[artifact], project_root=root)
            serialized = json.dumps(export)
            validation = validate_usage_export(export)

            self.assertEqual(validation["status"], "PASS")
            self.assertIn("<redacted-local-path>", serialized)
            self.assertIn("<redacted-secret>", serialized)
            self.assertNotIn("/Vol" + "umes/private", serialized)
            self.assertNotIn("gh" + "p_example", serialized)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
