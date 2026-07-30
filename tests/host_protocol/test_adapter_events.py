from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.cli import main  # noqa: E402
from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.host_protocol import (  # noqa: E402
    build_adapter_event_stream,
    build_event_stream_receipt,
    require_adapter_event_stream_pass,
    validate_adapter_event_stream,
    validate_event_capture_conformance,
)


class AdapterEventStreamTests(unittest.TestCase):
    def test_completed_stream_covers_launch_command_writes_usage_and_completion(self) -> None:
        result = validate_adapter_event_stream(_completed_stream())

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["terminalEvent"], "task.completed")
        self.assertEqual(result["eventCount"], 6)
        self.assertIn("usage.reported", result["eventTypes"])

    def test_blocked_stream_can_end_without_completion_overclaim(self) -> None:
        stream = _base_stream() + [
            _event(3, "task.blocked", "BLOCKED", payload={"blocker": "external action required"}),
        ]

        result = validate_adapter_event_stream(stream)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["terminalEvent"], "task.blocked")

    def test_stream_rejects_missing_terminal_event(self) -> None:
        result = validate_adapter_event_stream(_base_stream())

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("adapter-event-terminal-count", {item["code"] for item in result["blockers"]})
        with self.assertRaises(LifecycleError) as raised:
            require_adapter_event_stream_pass(result)
        self.assertEqual(raised.exception.code, "adapter-event-validation-failed")

    def test_stream_rejects_lineage_drift(self) -> None:
        stream = _completed_stream()
        stream[2]["taskId"] = "WS-OTHER"

        result = validate_adapter_event_stream(stream)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("adapter-event-lineage-mismatch", {item["code"] for item in result["blockers"]})

    def test_stream_rejects_events_after_terminal(self) -> None:
        stream = _completed_stream()
        stream.append(_event(7, "usage.reported", "PASS"))

        result = validate_adapter_event_stream(stream)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("adapter-event-after-terminal", {item["code"] for item in result["blockers"]})

    def test_stream_rejects_failed_command_hidden_by_completion(self) -> None:
        stream = _completed_stream()
        stream[2]["status"] = "FAIL"
        stream[2]["payload"]["exitCode"] = 2

        result = validate_adapter_event_stream(stream)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("adapter-event-failed-command-completed", {item["code"] for item in result["blockers"]})

    def test_event_capture_receipt_binds_stream_and_descriptor(self) -> None:
        descriptor = _descriptor()
        stream = build_adapter_event_stream(
            host="claude-code",
            adapter_id="claude",
            run_id="run-1",
            task_id="WS05-01",
            operation_id="op-1",
            command="python -m unittest",
            exit_code=0,
            changed_files=["src/agent_lifecycle/example.py"],
            usage={"inputTokens": 100, "outputTokens": 20},
            result_path="tasks/WS-01/attempt-1/task-result.json",
            recorded_at="2026-07-29T08:00:00Z",
        )
        receipt = build_event_stream_receipt(stream, descriptor=descriptor, producer_id="claude-event-producer")

        validation = validate_event_capture_conformance(descriptor=descriptor, capability_manifest=_capability_manifest(), events=stream, receipt=receipt)

        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(validation["declaredEventCapture"])
        self.assertEqual(validation["eventCount"], 6)

    def test_event_capture_rejects_stale_receipt_digest(self) -> None:
        descriptor = _descriptor()
        stream = _completed_stream()
        receipt = build_event_stream_receipt(stream, descriptor=descriptor, producer_id="claude-event-producer")
        stream[3]["payload"]["changedFiles"] = ["src/agent_lifecycle/other.py"]

        validation = validate_event_capture_conformance(descriptor=descriptor, capability_manifest=_capability_manifest(), events=stream, receipt=receipt)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("adapter-event-stream-stale", {item["code"] for item in validation["blockers"]})

    def test_adapter_event_check_cli_validates_event_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for event in _completed_stream():
                path = Path(tmp) / f"{event['sequence']}.json"
                path.write_text(json.dumps(event), encoding="utf-8")
                paths.extend(["--event", str(path)])

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(["adapter", "event-check", *paths])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")

    def test_adapter_event_capture_check_cli_validates_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor = _descriptor()
            manifest = _capability_manifest()
            stream = _completed_stream()
            receipt = build_event_stream_receipt(stream, descriptor=descriptor, producer_id="claude-event-producer")
            descriptor_path = root / "descriptor.json"
            manifest_path = root / "capability.json"
            receipt_path = root / "receipt.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            event_args = []
            for event in stream:
                path = root / f"{event['sequence']}.json"
                path.write_text(json.dumps(event), encoding="utf-8")
                event_args.extend(["--event", str(path)])
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = main(
                    [
                        "adapter",
                        "event-capture-check",
                        "--descriptor",
                        str(descriptor_path),
                        "--capability-manifest",
                        str(manifest_path),
                        "--receipt",
                        str(receipt_path),
                        *event_args,
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")


def _completed_stream() -> list[dict[str, object]]:
    return _base_stream() + [
        _event(3, "command.completed", "PASS", payload={"command": "python -m unittest", "exitCode": 0}),
        _event(4, "writes.summarized", "PASS", payload={"changedFiles": ["src/agent_lifecycle/example.py"]}),
        _event(5, "usage.reported", "PASS", payload={"inputTokens": 100, "outputTokens": 20}),
        _event(6, "task.completed", "PASS", payload={"resultPath": "tasks/WS-01/attempt-1/task-result.json"}),
    ]


def _base_stream() -> list[dict[str, object]]:
    return [
        _event(1, "session.started", "INFO", payload={"surface": "claude-code"}),
        _event(2, "task.launched", "PASS", payload={"packet": "tasks/release-0-5/workflow/task-packets/WS05-01.task-packet.json"}),
    ]


def _event(
    sequence: int,
    event_type: str,
    status: str,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": "agent-adapter-event.v1",
        "eventId": f"evt-{sequence}",
        "host": "claude-code",
        "adapterId": "claude",
        "runId": "run-1",
        "taskId": "WS05-01",
        "operationId": "op-1",
        "sequence": sequence,
        "eventType": event_type,
        "status": status,
        "recordedAt": f"2026-07-29T08:00:0{sequence}Z",
        "payload": payload or {},
    }


def _descriptor() -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-host-adapter.v1",
        "adapterId": "claude",
        "host": "claude-code",
        "maturity": "VERIFIED",
        "liveTestedHostRange": {"evidence": ["evidence.json"]},
        "contractCompatibility": {"rangeKind": "closed-offline"},
        "unsupportedOperationPolicy": "fail-closed",
        "coreSemantics": "delegated-to-agent-lifecycle-core",
        "operations": [{"name": "adapter-event-stream", "mapping": "agent-adapter-event.v1", "offlineConformance": "deterministic"}],
    }


def _capability_manifest() -> dict[str, object]:
    return {
        "schemaVersion": "agent-adapter-capability-manifest.v1",
        "adapterId": "claude",
        "host": "claude-code",
        "eventCapture": {"status": "DECLARED"},
        "capabilities": [{"name": "adapter-event-stream"}],
    }


if __name__ == "__main__":
    unittest.main()
