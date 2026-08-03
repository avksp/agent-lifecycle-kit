from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli, canonical_digest
except ImportError:
    from helpers import _run_cli, canonical_digest


class CliWorkflowManagedRunTests(unittest.TestCase):
    def test_workflow_run_writes_receipt_without_mutating_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root)
            out_path = root / "managed-run-receipt.json"
            before = state_path.read_text(encoding="utf-8")

            code, payload = _run_cli(
                [
                    "workflow",
                    "run",
                    "--state",
                    str(state_path),
                    "--manifest",
                    str(manifest_path),
                    "--operation-id",
                    "managed-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "next step",
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["nextAction"]["type"], "launch-tasks")
            self.assertFalse(payload["modelCallsStarted"])
            self.assertEqual(state_path.read_text(encoding="utf-8"), before)
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["receiptDigest"], payload["receiptDigest"])

    def test_workflow_run_reports_fail_closed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root)

            code, payload = _run_cli(
                [
                    "workflow",
                    "run",
                    "--state",
                    str(state_path),
                    "--manifest",
                    str(manifest_path),
                    "--operation-id",
                    "managed-op",
                    "--expected-revision",
                    "99",
                    "--source-revision",
                    "source",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["nextAction"]["type"], "blocked")
            self.assertIn("state-revision-mismatch", {item["code"] for item in payload["blockers"]})


def _write_bundle(root: Path) -> tuple[Path, Path]:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"]}],
        "acceptanceCriteria": [{"id": "AC-01", "evidenceIds": ["EV-01"]}],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (manifest_path.parent / "plan.lock.json").write_text(
        json.dumps({"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": digest}),
        encoding="utf-8",
    )
    state_path = root / "run.state.json"
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": digest,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": "RUNNING",
                "authorization": {"required": False, "granted": True},
                "tasks": [
                    {
                        "id": "WS-01",
                        "status": "READY",
                        "attempt": 0,
                        "dependsOn": [],
                        "required": True,
                        "artifactPaths": {
                            "result": "work/WS-01/attempt-{attempt}/task-result.json",
                            "review": "work/WS-01/attempt-{attempt}/task-review.json",
                        },
                        "packet": {"sha256": "1" * 64},
                    }
                ],
                "eventLog": "events.jsonl",
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, state_path


if __name__ == "__main__":
    unittest.main()
