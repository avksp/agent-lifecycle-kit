from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.contracts.workflow_continuation_schemas import (
    build_workflow_continuation_authority_projection,
)


class WorkflowContinuationSchemaTests(unittest.TestCase):
    def test_continuation_schemas_are_registered_and_bounded(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-workflow-continuation-action.v1", ids)
        self.assertIn("agent-workflow-continuation-receipt.v1", ids)
        self.assertIn("agent-workflow-continuation-authority-projection.v1", ids)

        action = get_schema("agent-workflow-continuation-action.v1")
        receipt = get_schema("agent-workflow-continuation-receipt.v1")
        self.assertEqual(action["properties"]["actionDigest"]["maxLength"], 64)
        self.assertEqual(receipt["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(receipt["properties"]["requiredInputs"]["maxItems"], 32)

    def test_batch_schemas_are_registered_and_closed(self) -> None:
        bundle = get_schema("agent-workflow-continuation-input-bundle.v1")
        receipt = get_schema("agent-workflow-continuation-batch-receipt.v1")
        summary = get_schema("agent-workflow-continuation-batch-summary.v1")

        self.assertEqual(bundle["properties"]["steps"]["maxItems"], 128)
        self.assertFalse(bundle["additionalProperties"])
        self.assertFalse(bundle["properties"]["steps"]["items"]["additionalProperties"])
        self.assertEqual(receipt["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(receipt["properties"]["hostLaunchStarted"], {"const": False})
        self.assertEqual(summary["properties"]["blockers"]["maxItems"], 64)
        self.assertIn("RETRY_PROOF_MISMATCH", summary["properties"]["stopReason"]["enum"])

    def test_authority_projection_normalizes_only_approved_observation_times(self) -> None:
        state = {
            "startedAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:01Z",
            "operationLedger": {"op": {"stateRevision": 2, "recordedAt": "2026-01-01T00:00:02Z"}},
        }
        events = [{"operationId": "op", "recordedAt": "2026-01-01T00:00:03Z", "payload": {}}]
        observation_changed = build_workflow_continuation_authority_projection(
            {
                **state,
                "updatedAt": "2026-02-01T00:00:01Z",
                "operationLedger": {"op": {"stateRevision": 2, "recordedAt": "2026-02-01T00:00:02Z"}},
            },
            [{"operationId": "op", "recordedAt": "2026-02-01T00:00:03Z", "payload": {}}],
        )
        authority_changed = build_workflow_continuation_authority_projection(
            {**state, "startedAt": "2026-03-01T00:00:00Z"},
            events,
        )
        baseline = build_workflow_continuation_authority_projection(state, events)

        self.assertEqual(baseline, observation_changed)
        self.assertNotEqual(baseline["projectionDigest"], authority_changed["projectionDigest"])

    def test_authority_projection_rejects_missing_invalid_and_non_monotonic_observations(self) -> None:
        valid_state = {
            "updatedAt": "2026-01-01T00:00:01Z",
            "operationLedger": {"op": {"stateRevision": 2, "recordedAt": "2026-01-01T00:00:02Z"}},
        }
        valid_events = [
            {
                "operationId": "op",
                "recordedAt": "2026-01-01T00:00:03Z",
                "payload": {},
            }
        ]
        cases = (
            ({"operationLedger": {}}, [], "continuation-observation-time-invalid"),
            (
                {**valid_state, "updatedAt": "2026-01-01T00:00:01+00:00"},
                valid_events,
                "continuation-observation-time-invalid",
            ),
            (
                valid_state,
                [
                    *valid_events,
                    {"recordedAt": "2026-01-01T00:00:02Z", "payload": {}},
                ],
                "continuation-observation-time-non-monotonic",
            ),
        )
        for state, events, expected_code in cases:
            with self.subTest(expected_code=expected_code), self.assertRaises(LifecycleError) as raised:
                build_workflow_continuation_authority_projection(state, events)
            self.assertEqual(raised.exception.code, expected_code)

    def test_authority_projection_rejects_malformed_event_payload_with_typed_error(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            build_workflow_continuation_authority_projection(
                {"updatedAt": "2026-01-01T00:00:01Z", "operationLedger": {}},
                [{"recordedAt": "2026-01-01T00:00:02Z", "payload": "invalid"}],
            )
        self.assertEqual(raised.exception.code, "continuation-authority-projection-invalid")


if __name__ == "__main__":
    unittest.main()
