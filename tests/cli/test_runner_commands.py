from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import _run_cli  # noqa: E402
except ImportError:
    from helpers import _run_cli  # noqa: E402


class RunnerCommandTests(unittest.TestCase):
    def test_runner_start_status_transition_stop_and_resume_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_workflow_state(root)
            runner_path = root / "runner.state.json"

            code, payload = _run_cli([
                "runner",
                "start",
                "--state",
                str(state_path),
                "--runner",
                str(runner_path),
                "--operation-id",
                "runner-init",
                "--reason",
                "start bounded loop",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-runner-state-validation.v1")
            self.assertEqual(payload["runnerStatus"], "READY")

            request_path = _write_request(root, "attempt", 1)
            code, payload = _run_cli(["runner", "transition", "--runner", str(runner_path), "--state", str(state_path), "--request", str(request_path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-runner-transition-result.v1")
            self.assertEqual(payload["runnerStatus"], "ATTEMPTING")

            code, payload = _run_cli([
                "runner",
                "status",
                "--runner",
                str(runner_path),
                "--state",
                str(state_path),
                "--profile",
                str(ROOT / "profiles/small-context-profile.v1.json"),
                "--target-window",
                "4k-strict",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-runner-snapshot.v1")
            self.assertLessEqual(payload["estimatedTokens"], 450)

            code, payload = _run_cli([
                "runner",
                "stop",
                "--runner",
                str(runner_path),
                "--state",
                str(state_path),
                "--operation-id",
                "runner-stop",
                "--expected-runner-revision",
                "2",
                "--reason",
                "operator pause",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["runnerStatus"], "STOPPED")
            self.assertEqual(payload["allowedNextActions"], ["resume"])

            code, payload = _run_cli([
                "runner",
                "resume",
                "--runner",
                str(runner_path),
                "--state",
                str(state_path),
                "--operation-id",
                "runner-resume",
                "--expected-runner-revision",
                "3",
                "--reason",
                "continue",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["runnerStatus"], "ATTEMPTING")

    def test_runner_transition_cli_rejects_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_workflow_state(root)
            runner_path = root / "runner.state.json"
            self.assertEqual(
                _run_cli([
                    "runner",
                    "start",
                    "--state",
                    str(state_path),
                    "--runner",
                    str(runner_path),
                    "--operation-id",
                    "runner-init",
                    "--reason",
                    "start",
                ])[0],
                0,
            )
            request_path = _write_request(root, "attempt", 2)

            code, payload = _run_cli(["runner", "transition", "--runner", str(runner_path), "--state", str(state_path), "--request", str(request_path)])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "runner-revision-mismatch")

    def test_runner_status_cli_rejects_tampered_state_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_workflow_state(root)
            runner_path = root / "runner.state.json"
            self.assertEqual(
                _run_cli([
                    "runner",
                    "start",
                    "--state",
                    str(state_path),
                    "--runner",
                    str(runner_path),
                    "--operation-id",
                    "runner-init",
                    "--reason",
                    "start",
                ])[0],
                0,
            )
            runner_state = json.loads(runner_path.read_text(encoding="utf-8"))
            runner_state["currentTaskId"] = "WS-02"
            runner_path.write_text(json.dumps(runner_state), encoding="utf-8")

            code, payload = _run_cli(["runner", "status", "--runner", str(runner_path), "--state", str(state_path)])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "runner-state-digest-mismatch")


def _write_workflow_state(root: Path) -> Path:
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 3,
        "phase": "RUNNING",
        "tasks": [
            {
                "id": "WS-01",
                "status": "READY",
                "attempt": 0,
                "required": True,
                "writes": ["src"],
            }
        ],
    }
    path = root / "run.state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _write_request(root: Path, action: str, revision: int) -> Path:
    request = {
        "schemaVersion": "agent-runner-transition-request.v1",
        "operationId": f"{action}-{revision}",
        "expectedRunnerRevision": revision,
        "action": action,
        "taskId": "WS-01",
        "reason": f"{action} transition",
    }
    path = root / f"{action}-{revision}.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
