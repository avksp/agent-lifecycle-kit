from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, canonical_digest  # noqa: E402
from agent_lifecycle.contracts.workflow_authorization_schemas import (  # noqa: E402
    validate_workflow_authorization_receipt,
)


class WorkflowAuthorizationSchemaTests(unittest.TestCase):
    def test_exact_lineage_and_digest_are_required(self) -> None:
        state = _state()
        receipt = _receipt(state)
        result = validate_workflow_authorization_receipt(
            receipt,
            state=state,
            now=datetime(2026, 8, 24, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(result["authorizedBy"], "release-lead")

        receipt["sourceRevision"] = "other"
        receipt["receiptDigest"] = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
        with self.assertRaises(LifecycleError) as raised:
            validate_workflow_authorization_receipt(receipt, state=state)
        self.assertEqual(raised.exception.code, "authorization-lineage-mismatch")

    def test_expired_receipt_is_rejected(self) -> None:
        state = _state()
        receipt = _receipt(state)
        with self.assertRaises(LifecycleError) as raised:
            validate_workflow_authorization_receipt(
                receipt,
                state=state,
                now=datetime(2026, 8, 24, 0, 2, tzinfo=UTC),
            )
        self.assertEqual(raised.exception.code, "authorization-expired")


def _state() -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 3,
        "planDigest": "a" * 64,
        "sourceRevision": "source",
        "stateRevision": 4,
    }


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
        "issuedAt": "2026-08-23T23:59:00Z",
        "expiresAt": "2026-08-24T00:01:00Z",
    }
    return {**body, "receiptDigest": canonical_digest(body)}


if __name__ == "__main__":
    unittest.main()
