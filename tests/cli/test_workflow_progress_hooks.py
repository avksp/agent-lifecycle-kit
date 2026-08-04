from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from agent_lifecycle.cli import main

try:
    from .helpers import _result, _review, _task, _write_state, canonical_digest, write_json_create
except ImportError:
    from helpers import _result, _review, _task, _write_state, canonical_digest, write_json_create


class WorkflowProgressHookCommandTests(unittest.TestCase):
    def test_workflow_run_hook_writes_stderr_without_changing_stdout_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root)

            code, stdout_payload, stderr_text = _run_cli_streams(
                [
                    "workflow",
                    "run",
                    "--state",
                    str(state_path),
                    "--manifest",
                    str(manifest_path),
                    "--operation-id",
                    "run-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--progress-hook",
                    "stderr",
                    "--progress-adapter",
                    "codex",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout_payload["schemaVersion"], "agent-managed-lifecycle-runner-receipt.v1")
        self.assertNotIn("agent-progress-hook-receipt.v1", json.dumps(stdout_payload))
        self.assertIn("RUNNING", stderr_text)
        self.assertIn("TOTAL", stderr_text)

    def test_workflow_transitions_can_write_progress_hook_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            _start_task(state_path)
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result()
            write_json_create(root / result_path, result)
            result_receipt = root / "receipts/result-progress.json"

            code, payload, stderr_text = _run_cli_streams(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--result",
                    result_path,
                    "--reason",
                    "done",
                    "--progress-hook",
                    "receipt",
                    "--progress-receipt",
                    str(result_receipt),
                    "--progress-adapter",
                    "codex",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(stderr_text, "")
            self.assertEqual(_task(payload)["status"], "VERIFYING")
            _assert_hook_receipt(result_receipt, "workflow task-result", "after-task-result")

            review_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, _review(canonical_digest(result)))
            accept_receipt = root / "receipts/accept-progress.json"
            code, payload, _stderr_text = _run_cli_streams(
                [
                    "workflow",
                    "task-accept",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "accept-op",
                    "--expected-revision",
                    "3",
                    "--review",
                    review_path,
                    "--reason",
                    "accepted",
                    "--progress-hook",
                    "receipt",
                    "--progress-receipt",
                    str(accept_receipt),
                    "--progress-adapter",
                    "codex",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "ACCEPTED")
            _assert_hook_receipt(accept_receipt, "workflow task-accept", "after-task-accept")

            final_audit = root / "final/final-audit.json"
            write_json_create(final_audit, _final_audit())
            finalize_receipt = root / "receipts/finalize-progress.json"
            code, payload, _stderr_text = _run_cli_streams(
                [
                    "workflow",
                    "finalize",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "finalize-op",
                    "--expected-revision",
                    "4",
                    "--source-revision",
                    "source",
                    "--final-audit",
                    "final/final-audit.json",
                    "--proof",
                    "final/proof.json",
                    "--reason",
                    "done",
                    "--progress-hook",
                    "receipt",
                    "--progress-receipt",
                    str(finalize_receipt),
                    "--progress-adapter",
                    "codex",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "COMPLETE")
            _assert_hook_receipt(finalize_receipt, "workflow finalize", "after-finalize")

    def test_missing_receipt_path_fails_before_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            _start_task(state_path)
            result_path = "work/WS-01/attempt-1/task-result.json"
            write_json_create(root / result_path, _result())
            before = state_path.read_text(encoding="utf-8")

            code, payload, _stderr_text = _run_cli_streams(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--result",
                    result_path,
                    "--reason",
                    "done",
                    "--progress-hook",
                    "receipt",
                ]
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "progress-hook-receipt-path-missing")
            self.assertEqual(state_path.read_text(encoding="utf-8"), before)

    def test_env_hook_is_stderr_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root)

            with mock.patch.dict(os.environ, {"ALK_PROGRESS_HOOK": "stderr"}):
                code, stdout_payload, stderr_text = _run_cli_streams(
                    [
                        "workflow",
                        "run",
                        "--state",
                        str(state_path),
                        "--manifest",
                        str(manifest_path),
                        "--operation-id",
                        "run-op",
                        "--expected-revision",
                        "1",
                        "--source-revision",
                        "source",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout_payload["schemaVersion"], "agent-managed-lifecycle-runner-receipt.v1")
        self.assertIn("RUNNING", stderr_text)


def _run_cli_streams(args: list[str]) -> tuple[int, dict, str]:
    stdout = StringIO()
    stderr = StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(args)
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def _start_task(state_path: Path) -> None:
    code, payload, stderr = _run_cli_streams(
        [
            "workflow",
            "task-start",
            "--state",
            str(state_path),
            "--task",
            "WS-01",
            "--operation-id",
            "start-op",
            "--expected-revision",
            "1",
            "--source-revision",
            "source",
            "--reason",
            "launch",
        ]
    )
    if code != 0:
        raise AssertionError(f"task-start failed: {payload}")
    if stderr:
        raise AssertionError(f"unexpected task-start stderr: {stderr}")


def _assert_hook_receipt(path: Path, command: str, hook_point: str) -> None:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    self = unittest.TestCase()
    self.assertEqual(receipt["schemaVersion"], "agent-progress-hook-receipt.v1")
    self.assertEqual(receipt["command"], command)
    self.assertEqual(receipt["hookPoint"], hook_point)
    self.assertEqual(receipt["hookMode"], "receipt")
    self.assertTrue(receipt["managedWorkflow"])
    self.assertTrue(receipt["autoClaimAllowed"])
    self.assertFalse(receipt["pluginInstalledIsLifecycleProof"])
    self.assertFalse(receipt["modelCallsStarted"])
    self.assertFalse(receipt["stateWritten"])
    self.assertIn("TOTAL", receipt["terminalText"])


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


def _final_audit() -> dict:
    return {
        "schemaVersion": "agent-final-candidate-audit.v1",
        "status": "PASS",
        "semanticStatus": "READY_FOR_FINALIZATION",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "productionPromotionClaimed": False,
        "completionSignal": {
            "schemaVersion": "agent-completion-signal.v1",
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
            "status": "PASS",
            "evidenceIds": ["EV-FINAL"],
            "verifier": {"id": "final-auditor", "independent": True},
            "completedAt": "2026-07-31T08:00:00Z",
        },
        "notAcceptedTasks": [],
        "missingReleaseEvidence": [],
        "findings": [],
    }


if __name__ == "__main__":
    unittest.main()
