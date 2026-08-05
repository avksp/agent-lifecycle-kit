from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest


class AdapterTaskCommandTests(unittest.TestCase):
    def test_task_start_file_writes_candidate_without_starting_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.md"
            candidate = root / "candidate.json"
            task.write_text("# Fix\n\n- Fix the failing checkout test\n", encoding="utf-8")

            code, payload, stderr = _run_cli(
                [
                    "adapter",
                    "task",
                    "start",
                    "--adapter",
                    "codex",
                    "--file",
                    str(task),
                    "--candidate-out",
                    str(candidate),
                ]
            )

            candidate_payload = json.loads(candidate.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "REVIEW_REQUIRED")
        self.assertFalse(payload["executionStarted"])
        self.assertEqual(candidate_payload["schemaVersion"], "agent-planning-import-result.v1")

    def test_task_start_aliases_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.md"
            task.write_text("# Task\n\n- Add docs\n", encoding="utf-8")

            code_file, payload_file, _stderr_file = _run_cli(
                ["adapter", "task", "start", "--adapter", "codex", "--task-file", str(task)]
            )
            code_text, payload_text, _stderr_text = _run_cli(
                ["adapter", "task", "start", "--adapter", "codex", "--task-text", "- Add docs"]
            )

        self.assertEqual(code_file, 0)
        self.assertEqual(code_text, 0)
        self.assertEqual(payload_file["status"], "REVIEW_REQUIRED")
        self.assertEqual(payload_text["status"], "REVIEW_REQUIRED")

    def test_frozen_manifest_file_with_binding_delegates_to_adapter_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, state = _write_bundle(root)

            code, payload, stderr = _run_cli(
                [
                    "adapter",
                    "task",
                    "start",
                    "--adapter",
                    "codex",
                    "--file",
                    str(manifest),
                    "--state",
                    str(state),
                    "--lock",
                    str(manifest.with_name("plan.lock.json")),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "adapter-task-start",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["action"], "MANAGED_RUN")
        self.assertTrue(payload["executionStarted"])
        self.assertTrue(payload["lifecycleCoverageClaimed"])
        self.assertEqual(payload["adapterSessionReceipt"]["schemaVersion"], "agent-adapter-session-receipt.v1")
        self.assertIn("RUNNING", stderr)

    def test_structured_run_request_delegates_to_adapter_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, state = _write_bundle(root)
            request = root / "run-request.json"
            request.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-adapter-task-run-request.v1",
                        "state": str(state),
                        "manifest": str(manifest),
                        "lock": str(manifest.with_name("plan.lock.json")),
                        "task": "WS-01",
                        "operationId": "adapter-task-start",
                        "expectedRevision": 1,
                        "sourceRevision": "source",
                    }
                ),
                encoding="utf-8",
            )

            code, payload, stderr = _run_cli(["adapter", "task", "start", "--adapter", "codex", "--file", str(request)])

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "READY")
        self.assertTrue(payload["executionStarted"])
        self.assertIn("RUNNING", stderr)


def _run_cli(args: list[str]) -> tuple[int, dict, str]:
    stdout = StringIO()
    stderr = StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(args)
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def _write_bundle(root: Path) -> tuple[Path, Path]:
    manifest_payload = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"]}],
        "acceptanceCriteria": [{"id": "AC-01", "evidenceIds": ["EV-01"]}],
    }
    digest = canonical_digest(manifest_payload)
    manifest = root / "plans/package/plan.manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    (manifest.parent / "plan.lock.json").write_text(
        json.dumps({"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": digest}),
        encoding="utf-8",
    )
    state = root / "state.json"
    state.write_text(
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
                "tasks": [{"id": "WS-01", "status": "READY", "attempt": 0, "dependsOn": [], "required": True}],
                "eventLog": "events.jsonl",
            }
        ),
        encoding="utf-8",
    )
    return manifest, state


if __name__ == "__main__":
    unittest.main()
