from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest


class AdapterSessionCommandTests(unittest.TestCase):
    def test_session_start_status_and_launch_blocked_by_wrapper_only_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"

            code, payload, stderr = _run_cli(
                ["adapter", "session", "start", "--adapter", "codex", "--session-root", str(sessions), "--launch"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertEqual(payload["launchReceipt"]["status"], "BLOCKED")

            code, status, _stderr = _run_cli(
                ["adapter", "session", "status", "--session", payload["sessionId"], "--session-root", str(sessions)]
            )

        self.assertEqual(code, 0)
        self.assertEqual(status["status"], "BLOCKED")
        self.assertFalse(status["lifecycleCoverageClaimed"])

    def test_session_start_blocks_custom_supported_descriptor_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            descriptor = root / "adapter.descriptor.json"
            descriptor.write_text(
                json.dumps(
                    {
                        "adapterId": "codex",
                        "managedLaunch": {
                            "status": "SUPPORTED",
                            "shell": False,
                            "timeoutSeconds": 5.0,
                            "env": {"allow": [], "allowPatterns": [], "projectPolicyAllowed": False},
                            "writesNativeConfig": False,
                            "promptInjectionDefault": False,
                            "argvTemplates": {"interactive": ["codex"], "managedTask": ["codex"], "resume": ["codex"]},
                        },
                    }
                ),
                encoding="utf-8",
            )

            code, payload, stderr = _run_cli(
                [
                    "adapter",
                    "session",
                    "start",
                    "--adapter",
                    "codex",
                    "--descriptor",
                    str(descriptor),
                    "--session-root",
                    str(sessions),
                    "--launch",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["hostLaunchStarted"])
        self.assertIn("adapter-generic-launch-disabled", {item["code"] for item in payload["launchReceipt"]["blockers"]})

    def test_adapter_run_preserves_stdout_json_and_prints_progress_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, state = _write_bundle(root)

            code, payload, stderr = _run_cli(
                [
                    "adapter",
                    "run",
                    "--adapter",
                    "codex",
                    "--session-root",
                    str(root / "sessions"),
                    "--state",
                    str(state),
                    "--manifest",
                    str(manifest),
                    "--lock",
                    str(manifest.with_name("plan.lock.json")),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "adapter-run",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-adapter-session-receipt.v1")
        self.assertTrue(payload["managedWorkflow"])
        self.assertIn("RUNNING", stderr)
        self.assertNotIn("agent-progress-hook-receipt.v1", json.dumps(payload))

    def test_session_promote_and_resume_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            _manifest, state = _write_bundle(root)
            code, started, _stderr = _run_cli(["adapter", "session", "start", "--adapter", "codex", "--session-root", str(sessions)])
            self.assertEqual(code, 0)

            code, promoted, stderr = _run_cli(
                [
                    "adapter",
                    "session",
                    "promote",
                    "--session",
                    started["sessionId"],
                    "--session-root",
                    str(sessions),
                    "--adapter",
                    "codex",
                    "--state",
                    str(state),
                    "--task",
                    "WS-01",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(promoted["status"], "READY")
            self.assertIn("RUNNING", stderr)

            code, resumed, _stderr = _run_cli(
                [
                    "adapter",
                    "session",
                    "resume",
                    "--session",
                    started["sessionId"],
                    "--session-root",
                    str(sessions),
                    "--adapter",
                    "codex",
                    "--state",
                    str(state),
                    "--task",
                    "WS-01",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(resumed["status"], "PASS")
        self.assertTrue(resumed["lifecycleCoverageClaimed"])


def _run_cli(args: list[str]) -> tuple[int, dict, str]:
    stdout = StringIO()
    stderr = StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(args)
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def _write_bundle(root: Path) -> tuple[Path, Path]:
    manifest_payload = {
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
