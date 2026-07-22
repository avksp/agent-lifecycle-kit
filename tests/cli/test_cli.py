from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle import __version__  # noqa: E402
from agent_lifecycle.cli import main  # noqa: E402
from agent_lifecycle.contracts import canonical_digest, write_json_create  # noqa: E402


class CliTests(unittest.TestCase):
    def test_version_outputs_compact_json(self) -> None:
        code, payload = _run_cli(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-version.v1")
        self.assertEqual(payload["version"], __version__)

    def test_schema_list_outputs_index(self) -> None:
        code, payload = _run_cli(["schema", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-schema-index.v1")
        self.assertTrue(payload["schemas"])

    def test_schema_show_outputs_schema(self) -> None:
        code, payload = _run_cli(["schema", "show", "agent-host-operation-request.v1"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["$id"], "agent-host-operation-request.v1")

    def test_reserved_group_fails_with_stable_error(self) -> None:
        code, payload = _run_cli(["plan"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(payload["code"], "command-not-implemented")

    def test_workflow_status_outputs_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp))
            code, payload = _run_cli(["workflow", "status", "--state", str(state_path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-workflow-status.v1")
            self.assertEqual(payload["nextAction"]["type"], "launch-tasks")

    def test_audit_ownership_outputs_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "plan.manifest.json"
            manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
            code, payload = _run_cli(
                [
                    "audit",
                    "ownership",
                    "--manifest",
                    str(manifest),
                    "--path",
                    "src/core.py",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-ownership-report.v1")
            self.assertEqual(payload["entries"][0]["owners"], ["WS-01"])

    def test_workflow_task_lifecycle_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            code, payload = _run_cli(
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
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "RUNNING")

            result_path = "tasks/WS-01/attempt-1/task-result.json"
            result = _result()
            write_json_create(root / result_path, result)
            code, payload = _run_cli(
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
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "VERIFYING")

            review_path = "tasks/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, _review(canonical_digest(result)))
            code, payload = _run_cli(
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
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "ACCEPTED")

    def test_context_profile_check_cli(self) -> None:
        code, payload = _run_cli([
            "context",
            "profile-check",
            "--profile",
            str(ROOT / "profiles/small-context-profile.v1.json"),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-small-context-profile-validation.v1")
        self.assertEqual(payload["defaultWindow"], "8k")

    def test_tier_resolve_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tier-request.json"
            path.write_text(
                json.dumps({
                    "schemaVersion": "agent-sdd-tier-resolution-request.v1",
                    "taskCount": 1,
                    "executableOwners": ["worker"],
                    "capabilityHints": ["bounded-mechanical"],
                    "riskFlags": {},
                    "requirementsBytes": 1200,
                    "externalSpecification": False,
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli(["tier", "resolve", "--request", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-sdd-tier-resolution.v1")
            self.assertEqual(payload["tier"], "S0")


def _run_cli(args: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(args)
    data = stdout.getvalue()
    return code, json.loads(data)


def _write_state(root: Path) -> Path:
    path = root / "run.state.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
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
                            "result": "tasks/WS-01/attempt-{attempt}/task-result.json",
                            "review": "tasks/WS-01/attempt-{attempt}/task-review.json",
                        },
                        "packet": {
                            "sha256": "1" * 64,
                        },
                    }
                ],
                "eventLog": "events.jsonl",
            }
        ),
        encoding="utf-8",
    )
    return path


def _task(payload: dict) -> dict:
    return next(item for item in payload["tasks"] if item["id"] == "WS-01")


def _result() -> dict:
    return {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "actor": "worker",
        "actorRunId": "worker-run",
        "surface": "test",
        "taskPacketHash": "1" * 64,
        "traceDigest": "2" * 64,
        "changedFiles": ["src/example.py"],
        "changeSet": {
            "provider": "git-worktree-v1",
            "baselineRef": "main",
            "baselineSha": "source",
            "fileSetHash": "3" * 64,
            "diffHash": "4" * 64,
            "snapshotHash": "5" * 64,
        },
        "commands": [],
        "itemOutcomes": [
            {
                "plannedItemId": "REQ-FOUNDATION",
                "status": "COMPLETE",
                "changedFiles": ["src/example.py"],
                "commandIds": [],
            }
        ],
        "summary": "done",
        "assumptions": [],
        "blocker": None,
        "contractChangeRequest": None,
    }


def _review(result_hash: str) -> dict:
    return {
        "schemaVersion": "agent-task-review.v2",
        "reviewId": "review-1",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": "0" * 64,
        "resultHash": result_hash,
        "taskPacketHash": "1" * 64,
        "traceDigest": "2" * 64,
        "reviewer": {
            "id": "reviewer",
            "independent": True,
            "surface": "test",
            "runId": "review-run",
        },
        "reviewedAt": "2026-07-22T00:00:00Z",
        "verdict": "ACCEPTED",
        "itemReviews": [
            {
                "plannedItemId": "REQ-FOUNDATION",
                "verdict": "ACCEPTED",
                "findingIds": [],
            }
        ],
        "acceptanceChecks": [
            {
                "acceptanceId": "AC-FOUNDATION",
                "status": "PASS",
                "evidenceIds": ["EV-FOUNDATION"],
                "findingIds": [],
            }
        ],
        "findings": [],
        "summary": "accepted",
    }


def _manifest() -> dict:
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "leadOwned": [],
        "readOnly": [],
        "forbiddenWrites": [],
        "workstreams": [{"id": "WS-01", "writes": ["src"]}],
    }


if __name__ == "__main__":
    unittest.main()
