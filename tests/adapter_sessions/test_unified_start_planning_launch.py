from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.planning_session import load_planning_session
from agent_lifecycle.adapter_sessions.unified_start import start_lifecycle
from agent_lifecycle.contracts import canonical_digest


class UnifiedStartPlanningLaunchTests(unittest.TestCase):
    def test_qualified_planning_launch_uses_default_profile_and_stops_at_review(self) -> None:
        raw = "Investigate the private failure and prepare a plan"
        launch_receipt = _planning_receipt(result_summary=f"Candidate for: {raw}")
        with tempfile.TemporaryDirectory() as tmp, patch(
            "agent_lifecycle.adapter_sessions.unified_start.start_adapter_task",
            return_value=_intake_receipt(raw),
        ), patch(
            "agent_lifecycle.adapter_sessions.unified_start.load_local_launch_profile",
            return_value=(Path(".alk/host-launch/codex.json"), {"adapterId": "codex"}, {"status": "PASS"}),
        ) as load_profile, patch(
            "agent_lifecycle.adapter_sessions.unified_start.launch_from_local_profile",
            return_value=launch_receipt,
        ) as launch:
            receipt = start_lifecycle(
                adapter_id="codex",
                mode="plan",
                task_text=raw,
                launch=True,
                session_root=Path(tmp),
            )
            session_id = receipt["delegate"]["planningSession"]["sessionId"]
            state = load_planning_session(session_id, session_root=Path(tmp), expected_adapter_id="codex")

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["action"], "DRAFT_PLAN_REVIEW")
        self.assertFalse(receipt["executionStarted"])
        self.assertFalse(receipt["lifecycleCoverageClaimed"])
        self.assertTrue(receipt["hostLaunchStarted"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertEqual(receipt["launchReceipt"]["action"], "PLANNING_LAUNCH")
        self.assertTrue(receipt["launchReceipt"]["modelCallsStarted"])
        self.assertEqual(state["state"], "REVIEW_REQUIRED")
        self.assertNotIn(raw, json.dumps(receipt))
        load_profile.assert_called_once_with(Path(".alk/host-launch/codex.json"))
        launch.assert_called_once()
        self.assertEqual(launch.call_args.kwargs["task_text"], raw)

    def test_missing_profile_blocks_with_preparation_and_resume_does_not_launch(self) -> None:
        raw = "prepare a review plan"
        with tempfile.TemporaryDirectory() as tmp, patch(
            "agent_lifecycle.adapter_sessions.unified_start.start_adapter_task",
            return_value=_intake_receipt(raw),
        ), patch(
            "agent_lifecycle.adapter_sessions.unified_start.load_local_launch_profile",
            side_effect=OSError("missing"),
        ), patch(
            "agent_lifecycle.adapter_sessions.unified_start.launch_from_local_profile"
        ) as launch:
            blocked = start_lifecycle(
                adapter_id="codex",
                task_text=raw,
                launch=True,
                session_root=Path(tmp),
            )
            session_id = blocked["delegate"]["planningSession"]["sessionId"]
            resumed = start_lifecycle(
                adapter_id="codex",
                resume_session_id=session_id,
                session_root=Path(tmp),
            )

        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["delegate"]["planningSession"]["state"], "BLOCKED")
        self.assertIn("profileCommand", blocked["blockers"][0])
        self.assertEqual(resumed["status"], "BLOCKED")
        self.assertFalse(resumed["nativeSessionAttached"])
        launch.assert_not_called()

    def test_without_launch_is_zero_host_and_raw_implement_is_blocked(self) -> None:
        raw = "plan only"
        with patch(
            "agent_lifecycle.adapter_sessions.unified_start.start_adapter_task",
            return_value=_intake_receipt(raw),
        ), patch(
            "agent_lifecycle.adapter_sessions.unified_start.launch_from_local_profile"
        ) as launch:
            draft = start_lifecycle(adapter_id="codex", task_text=raw)
            implement = start_lifecycle(adapter_id="codex", mode="implement", task_text=raw, launch=True)

        self.assertEqual(draft["status"], "REVIEW_REQUIRED")
        self.assertFalse(draft["hostLaunchStarted"])
        self.assertEqual(implement["blockers"][0]["code"], "start-implement-frozen-input-required")
        launch.assert_not_called()


def _intake_receipt(raw: str) -> dict[str, object]:
    return {
        "schemaVersion": "agent-adapter-task-start-receipt.v1",
        "status": "REVIEW_REQUIRED",
        "action": "DRAFT_INTAKE",
        "executionStarted": False,
        "lifecycleCoverageClaimed": False,
        "requiresReview": True,
        "reviewBlockers": [],
        "input": {"type": "TEXT", "label": "inline-task", "digest": "a" * 64, "byteCount": len(raw)},
        "receiptDigest": "d" * 64,
    }


def _planning_receipt(*, result_summary: str) -> dict[str, object]:
    body: dict[str, object] = {
        "schemaVersion": "agent-planning-launch-receipt.v1",
        "status": "REVIEW_REQUIRED",
        "action": "PLANNING_LAUNCH",
        "hostLaunchStarted": True,
        "modelCallsStarted": True,
        "blockers": [],
        "result": {"summary": result_summary},
    }
    return {**body, "receiptDigest": canonical_digest(body)}


if __name__ == "__main__":
    unittest.main()
