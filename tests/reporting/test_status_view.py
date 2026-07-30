from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting import build_status_view


class StatusViewTests(unittest.TestCase):
    def test_status_view_is_read_only_and_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/pass.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "blockers": []}), encoding="utf-8")

            view = build_status_view(project_root=root, artifact_paths=[Path("evidence/pass.json")], target_window="4k-strict")

        rendered = json.dumps(view, sort_keys=True)
        self.assertEqual(view["schemaVersion"], "agent-readonly-status-view.v1")
        self.assertEqual(view["status"], "PASS")
        self.assertFalse(view["sourceOfTruth"])
        self.assertEqual(view["targetWindow"], "4k-strict")
        self.assertLess(view["estimatedTokens"], 300)
        self.assertNotIn(str(root), rendered)

    def test_status_view_fails_on_failed_source_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/fail.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    {
                        "schemaVersion": "artifact.v1",
                        "status": "FAIL",
                        "blockers": [{"code": "missing-evidence"}],
                    }
                ),
                encoding="utf-8",
            )

            view = build_status_view(project_root=root, artifact_paths=[Path("evidence/fail.json")])

        self.assertEqual(view["status"], "FAIL")
        self.assertEqual(view["items"][0]["blockerCodes"], ["missing-evidence"])
        self.assertIn("status-view-artifact-failed", {item["code"] for item in view["blockers"]})


if __name__ == "__main__":
    unittest.main()
