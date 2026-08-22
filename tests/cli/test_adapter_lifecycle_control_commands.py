from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    build_lifecycle_control_attestation,
    build_lifecycle_control_decision,
    build_lifecycle_control_event,
    build_lifecycle_control_request,
)

ROOT = Path(__file__).resolve().parents[2]


class AdapterLifecycleControlCommandTests(unittest.TestCase):
    def test_lifecycle_control_check_accepts_bound_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            code, payload = _run_cli(
                [
                    "adapter",
                    "lifecycle-control-check",
                    "--policy",
                    str(ROOT / "policy/adapter-lifecycle-control.json"),
                    "--request",
                    str(bundle["request"]),
                    "--decision",
                    str(bundle["decision"]),
                    "--control-event",
                    str(bundle["event"]),
                    "--attestation",
                    str(bundle["attestation"]),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-adapter-lifecycle-control-validation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["blockers"], [])

    def test_lifecycle_control_check_rejects_request_lineage_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            decision = json.loads(bundle["decision"].read_text(encoding="utf-8"))
            decision["requestDigest"] = "d" * 64
            decision["decisionDigest"] = canonical_digest(
                {key: value for key, value in decision.items() if key != "decisionDigest"}
            )
            bundle["decision"].write_text(json.dumps(decision), encoding="utf-8")
            code, payload = _run_cli(
                [
                    "adapter",
                    "lifecycle-control-check",
                    "--policy",
                    str(ROOT / "policy/adapter-lifecycle-control.json"),
                    "--request",
                    str(bundle["request"]),
                    "--decision",
                    str(bundle["decision"]),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "lifecycle-control-validation-failed")
        self.assertIn("lifecycle-control-request-lineage-mismatch", _error_codes(payload))

    def test_lifecycle_control_check_rejects_wrong_attestation_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            attestation = json.loads(bundle["attestation"].read_text(encoding="utf-8"))
            attestation["domain"] = "wrong-domain"
            attestation["attestationDigest"] = canonical_digest(
                {key: value for key, value in attestation.items() if key != "attestationDigest"}
            )
            bundle["attestation"].write_text(json.dumps(attestation), encoding="utf-8")
            code, payload = _run_cli(
                [
                    "adapter",
                    "lifecycle-control-check",
                    "--policy",
                    str(ROOT / "policy/adapter-lifecycle-control.json"),
                    "--attestation",
                    str(bundle["attestation"]),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "lifecycle-control-validation-failed")
        self.assertIn("control-attestation-domain", _error_codes(payload))


def _run_cli(args: list[str]) -> tuple[int, dict[str, object]]:
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(args)
    return code, json.loads(stdout.getvalue())


def _write_bundle(root: Path) -> dict[str, Path]:
    now = datetime.now(UTC).replace(microsecond=0)

    def iso(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    request = build_lifecycle_control_request(
        request_id="request-1",
        adapter_id="claude",
        host="claude-code",
        host_version="1.2.3",
        operation="file-edit",
        run_id="run-1",
        task_id="task-1",
        package_id="package-1",
        plan_revision=1,
        plan_digest="a" * 64,
        lock_digest="b" * 64,
        state_revision=1,
        action_digest="c" * 64,
        paths=["src/example.py"],
        nonce="0123456789abcdef",
        created_at=iso(now),
    )
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
        producer_id="host-producer",
        outcome={"changed": False},
        recorded_at=iso(now),
    )
    attestation = build_lifecycle_control_attestation(
        attestation_id="attestation-1",
        producer_id="host-producer",
        adapter_id="claude",
        host_version="1.2.3",
        operation="file-edit",
        nonce="0123456789abcdef",
        issued_at=iso(now - timedelta(seconds=1)),
        expires_at=iso(now + timedelta(seconds=30)),
        plan_digest="a" * 64,
        lock_digest="b" * 64,
        state_revision=1,
        action_digest="c" * 64,
        outcome_digest="d" * 64,
        key_id="external-key-1",
        signature="external-signature",
    )
    result: dict[str, Path] = {}
    for name, value in (
        ("request", request),
        ("decision", decision),
        ("event", event),
        ("attestation", attestation),
    ):
        path = root / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        result[name] = path
    return result


def _error_codes(payload: dict[str, object]) -> set[str]:
    details = payload.get("details")
    if not isinstance(details, dict):
        return set()
    validation = details.get("validation")
    if not isinstance(validation, dict):
        return set()
    blockers = validation.get("blockers")
    if not isinstance(blockers, list):
        return set()
    return {item["code"] for item in blockers if isinstance(item, dict) and isinstance(item.get("code"), str)}


if __name__ == "__main__":
    unittest.main()
