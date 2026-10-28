"""Exact declared-user renewal contract, independent of the CLI parser."""

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.workflow_authorization_schemas import (
    WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT,
    WORKFLOW_AUTHORIZATION_SCHEMAS,
    authorization_renewal_bindings,
    validate_workflow_authorization_renewal_receipt,
)
from agent_lifecycle.workflow.state import load_state
from tests.workflow.test_authorization_renewal import build_fixture, renewal, seal


class RenewalSchemaTests(unittest.TestCase):
    def test_distinct_strict_schema_and_shared_bindings(self):
        schema = WORKFLOW_AUTHORIZATION_SCHEMAS[WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT]
        self.assertFalse(schema["additionalProperties"])
        state = {"budgets": {}, "tasks": [], "authorization": {}}
        self.assertIn("originalClocksDigest", authorization_renewal_bindings(state))

    def test_shape_types_dates_digests_predecessor_and_id_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _, _ = build_fixture(root)
            state = load_state(path)
            previous = json.loads((root / "old-authorization.json").read_bytes())
            receipt = renewal(state)
            now = datetime(2026, 10, 27, tzinfo=UTC)
            validate_workflow_authorization_renewal_receipt(receipt, state=state, previous_receipt=previous, now=now)
            variants = [
                {"stateRevision": True},
                {"planRevision": 1.0},
                {"reason": ""},
                {"authorizedBy": 123},
                {"issuedAt": "2026-01-01T00:00:00"},
                {"issuedAt": "invalid"},
                {"expiresAt": "2091-01-01T00:00:00"},
                {"expiresAt": "2020-01-01T00:00:00Z"},
                {"purpose": "NEW_EXECUTION"},
                {"receiptDigest": "z" * 64},
                {"previousAuthorizationReceipt": {"path": "old-authorization.json", "bytes": True, "sha256": "a" * 64}},
                {"previousAuthorizationReceipt": {"path": "old-authorization.json", "bytes": 1, "sha256": "bad"}},
                {"originalClocksDigest": "A" * 64},
                {"schemaVersion": "agent-workflow-authorization-receipt.v1"},
                {"unknownRequiredShape": {}},
            ]
            for change in variants:
                with self.subTest(change=change), self.assertRaises(LifecycleError):
                    validate_workflow_authorization_renewal_receipt(
                        {
                            **seal({**receipt, **change}),
                            **({"receiptDigest": change["receiptDigest"]} if "receiptDigest" in change else {}),
                        },
                        state=state,
                        previous_receipt=previous,
                        now=now,
                    )
            for missing in receipt:
                value = deepcopy(receipt)
                del value[missing]
                with self.subTest(missing=missing), self.assertRaises(LifecycleError):
                    validate_workflow_authorization_renewal_receipt(
                        value, state=state, previous_receipt=previous, now=now
                    )
            with self.assertRaises(LifecycleError):
                validate_workflow_authorization_renewal_receipt(
                    receipt,
                    state=state,
                    previous_receipt=previous,
                    used_authorization_ids={receipt["authorizationId"]},
                    now=now,
                )

    def test_active_window_blocked_and_invalid_historical_grants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _, _ = build_fixture(root)
            original = load_state(path)
            previous = json.loads((root / "old-authorization.json").read_bytes())
            for change in (
                {"closingWindow": {"status": "ACTIVE"}},
                {"blocker": {"code": "technical"}},
                {"schemaVersion": "agent-workflow-state.v3"},
            ):
                state = {**original, **change}
                with self.subTest(change=change), self.assertRaises(LifecycleError):
                    validate_workflow_authorization_renewal_receipt(
                        renewal(state), state=state, previous_receipt=previous
                    )
            for change in (
                {"runId": "foreign"},
                {"authorizedBy": "wrong"},
                {"stateRevision": 999},
                {"expiresAt": "2002-01-01T00:00:00Z"},
                {"planDigest": "bad"},
            ):
                with self.subTest(change=change), self.assertRaises(LifecycleError):
                    validate_workflow_authorization_renewal_receipt(
                        renewal(original), state=original, previous_receipt=seal({**previous, **change})
                    )
