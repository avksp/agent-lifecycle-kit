from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.session_store import create_session, session_path
from agent_lifecycle.adapter_sessions.unified_start import start_lifecycle
from agent_lifecycle.contracts.compatibility import build_contract_policy, validate_contract_policy
from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class UnifiedStartContractTests(unittest.TestCase):
    def test_raw_text_is_review_gated_and_never_starts_execution(self) -> None:
        raw = "Investigate the checkout failure and prepare a plan"

        with (
            patch("agent_lifecycle.adapter_sessions.task_intake.managed_adapter_run") as managed_run,
            patch("agent_lifecycle.adapter_sessions.launcher.launch_from_descriptor") as host_launch,
            patch("agent_lifecycle.adapter_sessions.process.run_process") as process_run,
        ):
            receipt = start_lifecycle(adapter_id="codex", task_text=raw)

        self.assertEqual(receipt["schemaVersion"], "agent-lifecycle-start-receipt.v1")
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["action"], "DRAFT_INTAKE")
        self.assertFalse(receipt["executionStarted"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertFalse(receipt["lifecycleCoverageClaimed"])
        self.assertTrue(receipt["requiresReview"])
        self.assertEqual(receipt["delegate"]["riskAdvisory"]["requestedRisk"], "auto")
        self.assertFalse(receipt["delegate"]["riskAdvisory"]["executionProfileCreated"])
        self.assertNotIn(raw, json.dumps(receipt, ensure_ascii=False))
        managed_run.assert_not_called()
        host_launch.assert_not_called()
        process_run.assert_not_called()

    def test_non_implement_modes_reject_complete_frozen_input(self) -> None:
        request = _run_request()
        for mode in ("auto", "research", "plan", "review"):
            with self.subTest(mode=mode), patch("agent_lifecycle.adapter_sessions.task_intake.managed_adapter_run") as managed_run:
                receipt = start_lifecycle(adapter_id="codex", mode=mode, task_text=json.dumps(request))

            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][0]["code"], "start-mode-implement-required")
            self.assertFalse(receipt["executionStarted"])
            self.assertFalse(receipt["hostLaunchStarted"])
            managed_run.assert_not_called()

    def test_implement_rejects_raw_input_and_incomplete_bindings(self) -> None:
        raw = start_lifecycle(adapter_id="codex", mode="implement", task_text="Implement this now")
        incomplete = _run_request()
        incomplete.pop("lock")
        missing = start_lifecycle(adapter_id="codex", mode="implement", task_text=json.dumps(incomplete))

        self.assertEqual(raw["blockers"][0]["code"], "start-implement-frozen-input-required")
        self.assertEqual(missing["blockers"][0]["code"], "start-frozen-binding-missing")
        self.assertEqual(missing["blockers"][0]["fields"], ["lock"])

    def test_implement_delegates_complete_run_request_to_existing_managed_path(self) -> None:
        managed_receipt = {
            "schemaVersion": "agent-adapter-session-receipt.v1",
            "status": "READY",
            "blockers": [],
            "lifecycleCoverageClaimed": True,
            "hostLaunchStarted": False,
            "receiptDigest": "a" * 64,
        }
        with patch(
            "agent_lifecycle.adapter_sessions.task_intake.managed_adapter_run",
            return_value=managed_receipt,
        ) as managed_run:
            receipt = start_lifecycle(
                adapter_id="codex",
                mode="implement",
                task_text=json.dumps(_run_request()),
            )

        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(receipt["action"], "MANAGED_RUN")
        self.assertTrue(receipt["executionStarted"])
        self.assertTrue(receipt["lifecycleCoverageClaimed"])
        self.assertFalse(receipt["hostLaunchStarted"])
        managed_run.assert_called_once()
        self.assertEqual(managed_run.call_args.kwargs["requested_risk"], "auto")

    def test_implement_delegates_frozen_manifest_with_complete_bindings(self) -> None:
        managed_receipt = {
            "schemaVersion": "agent-adapter-session-receipt.v1",
            "status": "READY",
            "blockers": [],
            "lifecycleCoverageClaimed": True,
            "hostLaunchStarted": False,
            "receiptDigest": "a" * 64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(
                json.dumps({"schemaVersion": "agent-plan-manifest.v1", "status": "FROZEN"}),
                encoding="utf-8",
            )
            with patch(
                "agent_lifecycle.adapter_sessions.task_intake.managed_adapter_run",
                return_value=managed_receipt,
            ) as managed_run:
                receipt = start_lifecycle(
                    adapter_id="codex",
                    mode="implement",
                    task_file=manifest_path,
                    state_path=root / "state.json",
                    lock_path=root / "plan.lock.json",
                    task_id="WS-01",
                    operation_id="start-run",
                    expected_revision=1,
                    source_revision="source",
                )

        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(receipt["action"], "MANAGED_RUN")
        self.assertTrue(receipt["executionStarted"])
        managed_run.assert_called_once()
        self.assertEqual(managed_run.call_args.kwargs["manifest_path"], manifest_path)

    def test_resume_blocks_missing_mismatched_and_corrupt_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = start_lifecycle(adapter_id="codex", resume_session_id="missing", session_root=root)
            session = create_session(
                adapter_id="codex",
                mode="INTERACTIVE",
                status="WAITING_FOR_TASK",
                launch_profile={"status": "WRAPPER_ONLY"},
                session_root=root,
            )
            mismatch = start_lifecycle(
                adapter_id="claude",
                resume_session_id=session["sessionId"],
                session_root=root,
            )
            stored = json.loads(session_path(session["sessionId"], session_root=root).read_text(encoding="utf-8"))
            stored["stateIdentity"] = {"runId": "run"}
            session_path(session["sessionId"], session_root=root).write_text(json.dumps(stored), encoding="utf-8")
            corrupt = start_lifecycle(
                adapter_id="codex",
                resume_session_id=session["sessionId"],
                session_root=root,
            )

        self.assertEqual(missing["blockers"][0]["code"], "start-resume-session-missing")
        self.assertEqual(mismatch["blockers"][0]["code"], "start-resume-adapter-mismatch")
        self.assertEqual(corrupt["blockers"][0]["code"], "start-resume-lineage-invalid")

    def test_resume_rejects_every_explicit_non_auto_mode(self) -> None:
        for mode in ("research", "plan", "review", "implement"):
            with self.subTest(mode=mode):
                receipt = start_lifecycle(
                    adapter_id="codex",
                    resume_session_id="session",
                    mode=mode,
                )

            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][0]["code"], "start-resume-mode-invalid")
            self.assertFalse(receipt["executionStarted"])
            self.assertFalse(receipt["nativeSessionAttached"])

    def test_resume_accepts_persisted_managed_lineage_without_exposing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity = {
                "statePath": (root / "private-state.json").as_posix(),
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "b" * 64,
                "sourceRevision": "source",
                "stateRevision": 2,
                "phase": "RUNNING",
                "taskId": "WS-01",
            }
            proof = {
                "kind": "alk-managed-adapter-session",
                "status": "PASS",
                "command": "adapter run",
                "adapterId": "codex",
                "taskId": "WS-01",
                "stateIdentity": identity,
            }
            session = create_session(
                adapter_id="codex",
                mode="MANAGED_TASK",
                status="READY",
                launch_profile={"status": "WRAPPER_ONLY"},
                session_root=root / "sessions",
                state_identity=identity,
                managed_workflow_proof=proof,
            )

            receipt = start_lifecycle(
                adapter_id="codex",
                resume_session_id=session["sessionId"],
                session_root=root / "sessions",
            )

        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["action"], "RESUME")
        self.assertTrue(receipt["lifecycleCoverageClaimed"])
        self.assertFalse(receipt["nativeSessionAttached"])
        self.assertNotIn(root.as_posix(), json.dumps(receipt))

    def test_resume_unbound_alk_session_is_truthfully_unmanaged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = create_session(
                adapter_id="codex",
                mode="INTERACTIVE",
                status="WAITING_FOR_TASK",
                launch_profile={"status": "WRAPPER_ONLY"},
                session_root=root,
            )
            receipt = start_lifecycle(
                adapter_id="codex",
                resume_session_id=session["sessionId"],
                session_root=root,
            )

        self.assertEqual(receipt["status"], "UNMANAGED")
        self.assertFalse(receipt["lifecycleCoverageClaimed"])

    def test_public_schema_and_compatibility_row_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        schema = get_schema("agent-lifecycle-start-receipt.v1")
        policy = build_contract_policy()

        self.assertIn("agent-lifecycle-start-receipt.v1", ids)
        self.assertEqual(schema["properties"]["hostLaunchStarted"], {"const": False})
        self.assertEqual(schema["properties"]["nativeSessionAttached"], {"const": False})
        self.assertEqual(validate_contract_policy(policy)["status"], "PASS")
        self.assertIn(
            ("start", "agent-lifecycle-start-receipt.v1"),
            {(item["command"], item["schemaVersion"]) for item in policy["cliOutputs"]},
        )


def _run_request() -> dict[str, object]:
    return {
        "schemaVersion": "agent-adapter-task-run-request.v1",
        "adapterId": "codex",
        "state": "state.json",
        "manifest": "tasks/release/plan.manifest.json",
        "lock": "tasks/release/plan.lock.json",
        "task": "WS-01",
        "operationId": "start-run",
        "expectedRevision": 1,
        "sourceRevision": "source",
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    unittest.main()
