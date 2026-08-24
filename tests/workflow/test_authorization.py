from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create  # noqa: E402
from agent_lifecycle.workflow import authorize_execution, start_execution, status  # noqa: E402


class WorkflowAuthorizationTests(unittest.TestCase):
    def test_authorize_consumes_receipt_once_and_moves_to_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            write_json_create(root / "authorization.json", _receipt(state))

            payload = authorize_execution(
                state_path,
                operation_id="authorize-op",
                expected_revision=1,
                source_revision="source",
                receipt_path="authorization.json",
                reason="operator approved execution",
            )
            self.assertEqual(payload["phase"], "READY")
            self.assertTrue(payload["authorization"]["granted"])

            with self.assertRaises(LifecycleError) as raised:
                authorize_execution(
                    state_path,
                    operation_id="authorize-replay",
                    expected_revision=2,
                    source_revision="source",
                    receipt_path="authorization.json",
                    reason="replay",
                )
            self.assertEqual(raised.exception.code, "invalid-phase")

    def test_plan_only_cannot_start_or_request_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="PLAN_ONLY", start_mode="plan-only", granted=False, required=False)
            self.assertEqual(status(state_path)["nextAction"]["type"], "none")
            with self.assertRaises(LifecycleError) as raised:
                start_execution(
                    state_path,
                    operation_id="plan-only-start",
                    expected_revision=1,
                    source_revision="source",
                    reason="must remain planning-only",
                )
            self.assertEqual(raised.exception.code, "plan-only-not-executable")


def _write_state(
    root: Path,
    *,
    phase: str = "AWAITING_AUTHORIZATION",
    start_mode: str = "approval-required",
    granted: bool = False,
    required: bool = True,
) -> Path:
    state = {
        "schemaVersion": "agent-workflow-state.v4",
        "runId": "run",
        "packageId": "package",
        "planRevision": 3,
        "planDigest": "a" * 64,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": phase,
        "runStartedAt": "2026-08-24T00:00:00Z",
        "packageRoot": ".",
        "eventLog": "events.jsonl",
        "operationLedger": {},
        "authorization": {"required": required, "granted": granted},
        "startMode": start_mode,
        "budgets": {},
        "tasks": [],
        "blocker": None,
    }
    path = root / "run.state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _receipt(state: dict) -> dict:
    body = {
        "schemaVersion": "agent-workflow-authorization-receipt.v1",
        "status": "PASS",
        "decision": "ALLOW",
        "authorizationId": "auth-1",
        "runId": state["runId"],
        "packageId": state["packageId"],
        "planRevision": state["planRevision"],
        "planDigest": state["planDigest"],
        "sourceRevision": state["sourceRevision"],
        "stateRevision": state["stateRevision"],
        "authorizedBy": "release-lead",
        "issuedAt": "2099-08-23T23:59:00Z",
        "expiresAt": "2099-08-24T00:30:00Z",
    }
    return {**body, "receiptDigest": canonical_digest(body)}


if __name__ == "__main__":
    unittest.main()
