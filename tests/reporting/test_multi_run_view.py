from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from agent_lifecycle.reporting import build_multi_run_attention_view


class MultiRunViewTests(unittest.TestCase):
    def test_empty_selection_is_a_read_only_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            view = build_multi_run_attention_view(project_root=root, run_roots=[])
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

        self.assertEqual(view["status"], "PASS")
        self.assertEqual(view["sourceCount"], 0)
        self.assertEqual(view["attentionItems"], [])
        self.assertEqual(view["overlaps"], [])
        self.assertFalse(view["sourceOfTruth"])
        self.assertTrue(view["readOnly"])
        self.assertEqual(before, after)

    def test_projection_reports_attention_and_overlap_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = _write_run(
                root / "work" / "run-a",
                run_id="run-a",
                package_id="package-a",
                phase="STEP_REVIEW",
                task_status="VERIFYING",
                task_started="2026-08-23T00:00:00Z",
                ownership=["src/shared.py"],
            )
            second = _write_run(
                root / "work" / "run-b",
                run_id="run-b",
                package_id="package-b",
                phase="AWAITING_AUTHORIZATION",
                task_status="READY",
                ownership=["src/shared.py"],
            )

            kwargs = {
                "project_root": root,
                "run_roots": [second, first],
                "stale_after_seconds": 3600,
                "now": datetime(2026, 8, 25, tzinfo=UTC),
            }
            view = build_multi_run_attention_view(**kwargs)
            second_view = build_multi_run_attention_view(**kwargs)

        self.assertEqual(view, second_view)
        self.assertEqual(view["status"], "PASS")
        self.assertEqual(view["sourceCount"], 2)
        reasons = {(item["runId"], item["reasonCode"]) for item in view["attentionItems"]}
        self.assertIn(("run-a", "PENDING_REVIEW"), reasons)
        self.assertIn(("run-a", "STALE_ATTEMPT"), reasons)
        self.assertIn(("run-b", "USER_ACTION_REQUIRED"), reasons)
        self.assertEqual(len(view["overlaps"]), 1)
        self.assertEqual(view["overlaps"][0]["path"], "src/shared.py")
        self.assertTrue(view["overlaps"][0]["authorityRetained"])

    def test_invalid_root_is_reported_without_reading_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp)
            (outside / "run.state.json").write_text("not-json", encoding="utf-8")
            view = build_multi_run_attention_view(project_root=root, run_roots=[outside])

        self.assertEqual(view["status"], "FAIL")
        self.assertEqual(view["failedSourceCount"], 1)
        self.assertEqual(view["sources"][0]["status"], "FAIL")
        self.assertEqual(view["sources"][0]["blockers"][0]["code"], "multi-run-path-outside-root")
        self.assertNotIn(str(outside), json.dumps(view))


def _write_run(
    root: Path,
    *,
    run_id: str,
    package_id: str,
    phase: str,
    task_status: str,
    ownership: list[str],
    task_started: str | None = None,
) -> Path:
    root.mkdir(parents=True)
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": run_id,
        "packageId": package_id,
        "planRevision": 1,
        "planDigest": "1" * 64,
        "sourceRevision": "source-1",
        "stateRevision": 2,
        "phase": phase,
        "authorization": {"required": phase == "AWAITING_AUTHORIZATION", "granted": False},
        "budgets": {},
        "tasks": [
            {
                "id": "WS-01",
                "status": task_status,
                "attempt": 1,
                "required": True,
                "writes": ownership,
                "attemptStartedAt": task_started,
            }
        ],
        "operationLedger": {},
        "eventLog": "workflow-events.jsonl",
    }
    (root / "run.state.json").write_text(json.dumps(state), encoding="utf-8")
    (root / "workflow-events.jsonl").write_text(
        json.dumps({"eventType": "run-started", "runId": run_id}) + "\n", encoding="utf-8"
    )
    return root


if __name__ == "__main__":
    unittest.main()
