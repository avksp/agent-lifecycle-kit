from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.planning_session import (
    create_planning_session,
    load_planning_session,
    planning_session_path,
    transition_planning_session,
)
from agent_lifecycle.contracts import LifecycleError


class PlanningSessionTests(unittest.TestCase):
    def test_state_is_digest_only_and_reaches_review_required(self) -> None:
        raw = "private planning task"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = create_planning_session(
                adapter_id="codex",
                requested_mode="plan",
                input_summary={"source": "TEXT", "sha256": "a" * 64, "byteCount": len(raw)},
                session_root=root,
            )
            running = transition_planning_session(
                session_id=session["sessionId"],
                adapter_id="codex",
                expected_state="INTAKE_ACCEPTED",
                new_state="PLANNING_RUNNING",
                session_root=root,
            )
            reviewed = transition_planning_session(
                session_id=session["sessionId"],
                adapter_id="codex",
                expected_state="PLANNING_RUNNING",
                new_state="REVIEW_REQUIRED",
                session_root=root,
                planning_receipt={"receiptDigest": "b" * 64, "result": {"summary": "candidate"}},
            )
            stored = planning_session_path(session["sessionId"], session_root=root).read_text(encoding="utf-8")

        self.assertEqual(running["state"], "PLANNING_RUNNING")
        self.assertEqual(reviewed["state"], "REVIEW_REQUIRED")
        self.assertFalse(reviewed["implementationAuthorized"])
        self.assertFalse(reviewed["productionPromotionClaimed"])
        self.assertNotIn(raw, stored)

    def test_adapter_mismatch_invalid_transition_and_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = create_planning_session(
                adapter_id="codex",
                requested_mode="research",
                input_summary={"source": "FILE", "sha256": "c" * 64, "byteCount": 8},
                session_root=root,
            )
            with self.assertRaisesRegex(LifecycleError, "another adapter"):
                load_planning_session(session["sessionId"], session_root=root, expected_adapter_id="claude")
            with self.assertRaisesRegex(LifecycleError, "not allowed"):
                transition_planning_session(
                    session_id=session["sessionId"],
                    adapter_id="codex",
                    expected_state="INTAKE_ACCEPTED",
                    new_state="REVIEW_REQUIRED",
                    session_root=root,
                )
            path = planning_session_path(session["sessionId"], session_root=root)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["implementationAuthorized"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(LifecycleError) as raised:
                load_planning_session(session["sessionId"], session_root=root)

        self.assertEqual(raised.exception.code, "planning-session-authority-invalid")


if __name__ == "__main__":
    unittest.main()
