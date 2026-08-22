from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.cli import main  # noqa: E402
from agent_lifecycle.contracts import LifecycleError, canonical_digest  # noqa: E402
from agent_lifecycle.contracts.lifecycle_control_schemas import (  # noqa: E402
    build_default_lifecycle_control_policy,
    build_lifecycle_control_attestation,
    build_lifecycle_control_decision,
    build_lifecycle_control_event,
    build_lifecycle_control_request,
)
from agent_lifecycle.host_protocol import (  # noqa: E402
    build_adapter_event_stream,
    build_event_stream_receipt,
    require_adapter_event_stream_pass,
    validate_adapter_event_stream,
    validate_event_capture_conformance,
)
from agent_lifecycle.host_protocol.event_capture import (  # noqa: E402
    require_lifecycle_control_bundle_pass,
    validate_lifecycle_control_bundle,
)


class AdapterEventStreamTests(unittest.TestCase):
    def test_completed_stream_covers_launch_command_writes_usage_and_completion(self) -> None:
        result = validate_adapter_event_stream(_completed_stream())

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["terminalEvent"], "task.completed")
        self.assertEqual(result["eventCount"], 6)
        self.assertIn("usage.reported", result["eventTypes"])

    def test_blocked_stream_can_end_without_completion_overclaim(self) -> None:
        stream = [
            *_base_stream(),
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
            result_path="work/WS-01/attempt-1/task-result.json",
            recorded_at="2026-07-29T08:00:00Z",
        )
        receipt = build_event_stream_receipt(stream, descriptor=descriptor, producer_id="claude-event-producer")

        validation = validate_event_capture_conformance(
            descriptor=descriptor, capability_manifest=_capability_manifest(), events=stream, receipt=receipt
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(validation["declaredEventCapture"])
        self.assertEqual(validation["eventCount"], 6)

    def test_event_capture_rejects_stale_receipt_digest(self) -> None:
        descriptor = _descriptor()
        stream = _completed_stream()
        receipt = build_event_stream_receipt(stream, descriptor=descriptor, producer_id="claude-event-producer")
        stream[3]["payload"]["changedFiles"] = ["src/agent_lifecycle/other.py"]

        validation = validate_event_capture_conformance(
            descriptor=descriptor, capability_manifest=_capability_manifest(), events=stream, receipt=receipt
        )

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

    def test_codex_claude_and_opencode_event_fixtures_validate(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for adapter_id in ("codex", "claude", "opencode"):
            with self.subTest(adapter_id=adapter_id):
                descriptor = json.loads(
                    (root / "adapters" / adapter_id / "adapter.descriptor.json").read_text(encoding="utf-8")
                )
                capability_manifest = json.loads(
                    (root / "adapters" / adapter_id / "capabilities.manifest.json").read_text(encoding="utf-8")
                )
                events = json.loads(
                    (root / "conformance" / "adapters" / adapter_id / "event-stream.json").read_text(encoding="utf-8")
                )
                receipt = json.loads(
                    (root / "conformance" / "adapters" / adapter_id / "event-stream-receipt.json").read_text(
                        encoding="utf-8"
                    )
                )

                validation = validate_event_capture_conformance(
                    descriptor=descriptor,
                    capability_manifest=capability_manifest,
                    events=events,
                    receipt=receipt,
                )

                self.assertEqual(validation["status"], "PASS")
                self.assertTrue(validation["declaredEventCapture"])

    def test_lifecycle_control_bundle_binds_all_producer_surfaces(self) -> None:
        request = _control_request()
        decision = build_lifecycle_control_decision(
            request,
            status="PASS",
            effective_level="GUIDANCE_ONLY",
            host_action_allowed=False,
        )
        event = build_lifecycle_control_event(
            request,
            event_id="event-1",
            event_type="post-action",
            status="PASS",
            producer_id=request["producerId"],
            outcome={"changed": False},
        )
        attestation = _control_attestation(request)

        validation = validate_lifecycle_control_bundle(
            policy=build_default_lifecycle_control_policy(),
            request=request,
            decision=decision,
            events=[event],
            attestation=attestation,
            reference_time=datetime.now(UTC).replace(microsecond=0),
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertIs(require_lifecycle_control_bundle_pass(validation), validation)

    def test_lifecycle_control_bundle_rejects_request_lineage_drift(self) -> None:
        request = _control_request()
        event = build_lifecycle_control_event(
            request,
            event_id="event-1",
            event_type="post-action",
            status="PASS",
            producer_id="host-hook",
            outcome={"changed": False},
        )
        drifted = dict(event)
        drifted["requestDigest"] = "f" * 64
        drifted["eventDigest"] = "e" * 64

        validation = validate_lifecycle_control_bundle(
            policy=build_default_lifecycle_control_policy(),
            request=request,
            events=[drifted],
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "lifecycle-control-request-lineage-mismatch",
            {item["code"] for item in validation["blockers"]},
        )

    def test_lifecycle_control_bundle_rejects_attestation_and_decision_drift(self) -> None:
        request = _control_request()
        decision = build_lifecycle_control_decision(
            request,
            status="PASS",
            effective_level="GUIDANCE_ONLY",
            host_action_allowed=False,
        )
        decision["operation"] = "shell-command"
        decision["decisionDigest"] = canonical_digest(
            {key: value for key, value in decision.items() if key != "decisionDigest"}
        )
        attestation = _control_attestation(request)
        attestation["actionDigest"] = "d" * 64
        attestation["attestationDigest"] = canonical_digest(
            {key: value for key, value in attestation.items() if key != "attestationDigest"}
        )

        validation = validate_lifecycle_control_bundle(
            policy=build_default_lifecycle_control_policy(),
            request=request,
            decision=decision,
            attestation=attestation,
        )

        codes = {item["code"] for item in validation["blockers"]}
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("lifecycle-control-operation-lineage-mismatch", codes)
        self.assertIn("lifecycle-control-attestation-lineage-mismatch", codes)

    def test_lifecycle_control_bundle_rejects_mixed_event_batch_without_request(self) -> None:
        first_request = _control_request(request_id="request-1")
        second_request = _control_request(request_id="request-2")
        events = [
            build_lifecycle_control_event(
                first_request,
                event_id="event-1",
                event_type="pre-action",
                status="PASS",
                producer_id="host-hook",
                outcome={},
            ),
            build_lifecycle_control_event(
                second_request,
                event_id="event-2",
                event_type="post-action",
                status="PASS",
                producer_id="host-hook",
                outcome={},
            ),
        ]

        validation = validate_lifecycle_control_bundle(
            policy=build_default_lifecycle_control_policy(),
            events=events,
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "lifecycle-control-event-batch-lineage-mismatch",
            {item["code"] for item in validation["blockers"]},
        )

    def test_lifecycle_control_bundle_rejects_event_count_over_policy_limit(self) -> None:
        request = _control_request()
        events = [
            build_lifecycle_control_event(
                request,
                event_id=f"event-{index}",
                event_type="post-action",
                status="PASS",
                producer_id="host-hook",
                outcome={},
            )
            for index in range(65)
        ]

        validation = validate_lifecycle_control_bundle(
            policy=build_default_lifecycle_control_policy(),
            request=request,
            events=events,
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("control-event-batch-limit", {item["code"] for item in validation["blockers"]})

    def test_lifecycle_control_bundle_rejects_unbound_proof_and_camel_case_secret(self) -> None:
        request = _control_request()
        decision = build_lifecycle_control_decision(
            request,
            status="PASS",
            effective_level="GUIDANCE_ONLY",
            host_action_allowed=False,
        )
        event = build_lifecycle_control_event(
            request,
            event_id="event-1",
            event_type="post-action",
            status="PASS",
            producer_id=request["producerId"],
            outcome={},
        )
        event["outcome"] = {"apiToken": "secret"}
        event["eventDigest"] = canonical_digest({key: value for key, value in event.items() if key != "eventDigest"})

        unbound = validate_lifecycle_control_bundle(
            policy=build_default_lifecycle_control_policy(),
            decision=decision,
            attestation=_control_attestation(request),
        )
        secret = validate_lifecycle_control_bundle(
            policy=build_default_lifecycle_control_policy(),
            request=request,
            events=[event],
        )

        self.assertEqual(unbound["status"], "FAIL")
        self.assertIn("lifecycle-control-request-required-for-proof", {item["code"] for item in unbound["blockers"]})
        self.assertEqual(secret["status"], "FAIL")
        self.assertIn("lifecycle-control-unredacted-sensitive-value", {item["code"] for item in secret["blockers"]})


def _completed_stream() -> list[dict[str, object]]:
    return [
        *_base_stream(),
        _event(3, "command.completed", "PASS", payload={"command": "python -m unittest", "exitCode": 0}),
        _event(4, "writes.summarized", "PASS", payload={"changedFiles": ["src/agent_lifecycle/example.py"]}),
        _event(5, "usage.reported", "PASS", payload={"inputTokens": 100, "outputTokens": 20}),
        _event(6, "task.completed", "PASS", payload={"resultPath": "work/WS-01/attempt-1/task-result.json"}),
    ]


def _base_stream() -> list[dict[str, object]]:
    return [
        _event(1, "session.started", "INFO", payload={"surface": "claude-code"}),
        _event(
            2,
            "task.launched",
            "PASS",
            payload={"packet": "work/release-0-5/workflow/task-packets/WS05-01.task-packet.json"},
        ),
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
        "operations": [
            {"name": "adapter-event-stream", "mapping": "agent-adapter-event.v1", "offlineConformance": "deterministic"}
        ],
    }


def _capability_manifest() -> dict[str, object]:
    return {
        "schemaVersion": "agent-adapter-capability-manifest.v1",
        "adapterId": "claude",
        "host": "claude-code",
        "eventCapture": {"status": "DECLARED"},
        "capabilities": [{"name": "adapter-event-stream"}],
    }


def _control_request(*, request_id: str = "request-1") -> dict[str, Any]:
    return build_lifecycle_control_request(
        request_id=request_id,
        adapter_id="example",
        host="example-host",
        host_version="1.2.3",
        operation="file-edit",
        run_id="run-1",
        task_id="WS80-03",
        package_id="release-1-80",
        plan_revision=6,
        plan_digest="a" * 64,
        lock_digest="b" * 64,
        state_revision=17,
        action_digest="c" * 64,
        paths=["src/example.py"],
        nonce="0123456789abcdef",
    )


def _control_attestation(request: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    return build_lifecycle_control_attestation(
        attestation_id="attestation-1",
        producer_id=request["producerId"],
        adapter_id=request["adapterId"],
        host_version=request["hostVersion"],
        operation=request["operation"],
        nonce=request["nonce"],
        issued_at=(now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        expires_at=(now + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        plan_digest=request["planDigest"],
        lock_digest=request["lockDigest"],
        state_revision=request["stateRevision"],
        action_digest=request["actionDigest"],
        outcome_digest="e" * 64,
        key_id="external-key-1",
        signature="signature",
    )


if __name__ == "__main__":
    unittest.main()
