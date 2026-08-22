from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.workflow import start_task
from agent_lifecycle.workflow.task_transitions import _require_control_task_acceptance

from .helpers import _write_state


class TaskTransitionAuthorityTests(unittest.TestCase):
    def test_start_task_rejects_pseudo_glob_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["writes"] = ["src/**"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-invalid-authority",
                    expected_revision=1,
                    source_revision="source",
                    reason="test",
                )

            self.assertEqual(raised.exception.code, "invalid-authority-path")
            self.assertEqual(state_path.read_bytes(), before)

    def test_guidance_control_does_not_require_post_action_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["lifecycleControl"] = {
                "level": "GUIDANCE_ONLY",
                "source": "frozen-plan",
                "planDigest": state["planDigest"],
                "planRevision": state["planRevision"],
            }

            _require_control_task_acceptance(state, state["tasks"][0])

    def test_enforced_control_rejects_tampered_post_action_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["lifecycleControl"] = {
                "level": "ENFORCED",
                "source": "frozen-plan",
                "planDigest": state["planDigest"],
                "planRevision": state["planRevision"],
            }
            post_action = {
                "schemaVersion": "agent-lifecycle-control-gate.v1",
                "gateType": "post-action",
                "status": "PASS",
                "blocking": False,
                "selected": True,
                "enforcementActive": True,
                "blockers": [],
                "productionPromotionClaimed": False,
            }
            post_action["gateDigest"] = canonical_digest(post_action)
            post_action["status"] = "FAIL"
            state["tasks"][0]["lifecycleControlPostAction"] = post_action

            with self.assertRaises(LifecycleError) as raised:
                _require_control_task_acceptance(state, state["tasks"][0])

            self.assertEqual(raised.exception.code, "lifecycle-control-evidence-required")


if __name__ == "__main__":
    unittest.main()
