from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.workflow_bridge import (
    managed_adapter_run,
    promote_session_to_workflow,
    resume_adapter_session,
)
from agent_lifecycle.adapter_sessions.session_store import create_session
from agent_lifecycle.contracts import canonical_digest


class AdapterSessionWorkflowBridgeTests(unittest.TestCase):
    def test_managed_adapter_run_binds_frozen_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, state, descriptor = _write_bundle(root)

            receipt = managed_adapter_run(
                adapter_id="codex",
                descriptor_path=descriptor,
                session_root=root / "sessions",
                state_path=state,
                manifest_path=manifest,
                lock_path=manifest.with_name("plan.lock.json"),
                task_id="WS-01",
                operation_id="adapter-run",
                expected_revision=1,
                source_revision="source",
            )

        self.assertEqual(receipt["schemaVersion"], "agent-adapter-session-receipt.v1")
        self.assertEqual(receipt["status"], "READY")
        self.assertTrue(receipt["managedWorkflow"])
        self.assertTrue(receipt["lifecycleCoverageClaimed"])
        self.assertEqual(receipt["progressHookDefault"], "stderr")
        self.assertEqual(receipt["nextAction"]["type"], "launch-tasks")

    def test_promote_and_resume_require_matching_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest, state, _descriptor = _write_bundle(root)
            session = create_session(
                adapter_id="codex",
                mode="INTERACTIVE",
                status="WAITING_FOR_TASK",
                launch_profile={"status": "WRAPPER_ONLY"},
                session_root=root / "sessions",
            )

            promoted = promote_session_to_workflow(
                session_id=session["sessionId"],
                session_root=root / "sessions",
                adapter_id="codex",
                state_path=state,
                task_id="WS-01",
            )
            resumed = resume_adapter_session(
                session_id=session["sessionId"],
                session_root=root / "sessions",
                adapter_id="codex",
                state_path=state,
                task_id="WS-01",
            )
            blocked = resume_adapter_session(
                session_id=session["sessionId"],
                session_root=root / "sessions",
                adapter_id="claude",
                state_path=state,
                task_id="WS-01",
            )

        self.assertEqual(promoted["status"], "READY")
        self.assertEqual(resumed["status"], "PASS")
        self.assertTrue(resumed["lifecycleCoverageClaimed"])
        self.assertEqual(blocked["status"], "BLOCKED")


def _write_bundle(root: Path) -> tuple[Path, Path, Path]:
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
    descriptor = root / "adapter.descriptor.json"
    descriptor.write_text(
        json.dumps(
            {
                "adapterId": "codex",
                "managedLaunch": {
                    "status": "WRAPPER_ONLY",
                    "reason": "wrapper required",
                    "shell": False,
                    "timeoutSeconds": 30,
                    "env": {"allow": [], "allowPatterns": [], "projectPolicyAllowed": True},
                    "writesNativeConfig": False,
                    "promptInjectionDefault": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest, state, descriptor


if __name__ == "__main__":
    unittest.main()
