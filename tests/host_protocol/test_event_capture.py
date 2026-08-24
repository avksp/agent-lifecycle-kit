from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.lifecycle_control_schemas import build_adapter_action_evidence
from agent_lifecycle.host_protocol.event_capture import (
    build_adapter_event_stream,
    build_event_stream_receipt,
    validate_event_capture_receipt,
    validate_observed_action_trace,
)


class AdapterActionEvidenceTests(unittest.TestCase):
    def test_observed_trace_binds_request_permission_and_result(self) -> None:
        evidence = _evidence()
        events = build_adapter_event_stream(
            host="claude-code",
            adapter_id="claude",
            run_id="run-1",
            task_id="WS87-01",
            operation_id="op-1",
            command="python -m unittest",
            exit_code=0,
            result_path="work/WS87-01/attempt-1/task-result.json",
            action_evidence=evidence,
        )
        descriptor = {"adapterId": "claude", "host": "claude-code"}

        trace = validate_observed_action_trace(events, descriptor=descriptor)
        receipt = build_event_stream_receipt(
            events,
            descriptor=descriptor,
            producer_id="claude-event-producer",
            require_observed=True,
        )
        validation = validate_event_capture_receipt(receipt, events, descriptor=descriptor, require_observed=True)

        self.assertEqual(trace["status"], "PASS")
        self.assertEqual(receipt["evidenceLevel"], "OBSERVED")
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["actionEvidenceDigest"], evidence["actionEvidenceDigest"])

    def test_missing_event_evidence_is_unavailable(self) -> None:
        events = build_adapter_event_stream(
            host="claude-code",
            adapter_id="claude",
            run_id="run-1",
            task_id="WS87-01",
            operation_id="op-1",
            command="python -m unittest",
            exit_code=0,
            result_path="work/WS87-01/attempt-1/task-result.json",
            action_evidence=_evidence(),
        )
        del events[3]["payload"]["actionEvidence"]

        validation = validate_observed_action_trace(events)

        self.assertEqual(validation["status"], "FAIL")
        self.assertEqual(validation["evidenceLevel"], "UNAVAILABLE")
        self.assertIn("adapter-action-evidence-missing", {item["code"] for item in validation["blockers"]})

    def test_evidence_drift_and_result_mismatch_fail_closed(self) -> None:
        events = build_adapter_event_stream(
            host="claude-code",
            adapter_id="claude",
            run_id="run-1",
            task_id="WS87-01",
            operation_id="op-1",
            command="python -m unittest",
            exit_code=0,
            result_path="work/WS87-01/attempt-1/task-result.json",
            action_evidence=_evidence(),
        )
        changed = dict(events[2]["payload"]["actionEvidence"])
        changed["userRequestId"] = "request-replayed"
        changed["actionEvidenceDigest"] = canonical_digest(
            {key: value for key, value in changed.items() if key != "actionEvidenceDigest"}
        )
        events[2]["payload"]["actionEvidence"] = changed
        events[-1]["payload"]["resultPath"] = "work/other-result.json"

        validation = validate_observed_action_trace(events)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("adapter-action-evidence-chain-drift", codes)
        self.assertIn("adapter-action-evidence-result-lineage-mismatch", codes)


def _evidence() -> dict[str, object]:
    return build_adapter_action_evidence(
        user_request_id="request-1",
        operation_lineage={"runId": "run-1", "taskId": "WS87-01", "operationId": "op-1"},
        profile_digest="a" * 64,
        effective_config_digest="b" * 64,
        capability_digest="c" * 64,
        permission_decision={"status": "ALLOW", "source": "host"},
        tool_category="command",
        result_link={
            "kind": "task-result",
            "ref": "work/WS87-01/attempt-1/task-result.json",
            "digest": "d" * 64,
        },
    )


if __name__ == "__main__":
    unittest.main()
