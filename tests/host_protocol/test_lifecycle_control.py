from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_lifecycle.contracts.lifecycle_control_schemas import (
    build_default_lifecycle_control_policy,
    build_lifecycle_control_attestation,
    build_lifecycle_control_decision,
    build_lifecycle_control_event,
    build_lifecycle_control_qualification_receipt,
    build_lifecycle_control_request,
)
from agent_lifecycle.host_protocol.lifecycle_control import (
    effective_control_level,
    lifecycle_control_is_enforced,
    load_lifecycle_control_policy,
    require_lifecycle_control_decision_pass,
    require_lifecycle_control_event_pass,
    require_lifecycle_control_policy_pass,
    validate_lifecycle_control_attestation_with_policy,
    validate_lifecycle_control_decision_with_policy,
    validate_lifecycle_control_event,
    validate_lifecycle_control_event_batch_with_policy,
    validate_lifecycle_control_event_with_policy,
    validate_lifecycle_control_policy,
    validate_lifecycle_control_qualification_with_policy,
    validate_lifecycle_control_request_with_policy,
)


class LifecycleControlHostProtocolTests(unittest.TestCase):
    def test_default_policy_is_not_enforced(self) -> None:
        policy = build_default_lifecycle_control_policy()

        self.assertEqual(effective_control_level(policy, "shell-command"), "GUIDANCE_ONLY")
        self.assertFalse(lifecycle_control_is_enforced(policy, "shell-command"))

    def test_policy_loader_validates_before_returning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(json.dumps(build_default_lifecycle_control_policy()), encoding="utf-8")

            loaded = load_lifecycle_control_policy(path)

        self.assertEqual(validate_lifecycle_control_policy(loaded)["status"], "PASS")

        repository_policy = Path(__file__).resolve().parents[2] / "policy" / "adapter-lifecycle-control.json"
        loaded_repository_policy = load_lifecycle_control_policy(repository_policy)
        self.assertEqual(validate_lifecycle_control_policy(loaded_repository_policy)["status"], "PASS")

    def test_decision_and_event_requirements_validate_the_full_chain(self) -> None:
        request = build_lifecycle_control_request(
            request_id="request-1",
            adapter_id="example",
            host="example-host",
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
        )
        decision = build_lifecycle_control_decision(
            request,
            status="PASS",
            effective_level="GUIDANCE_ONLY",
            host_action_allowed=False,
        )
        self.assertIs(require_lifecycle_control_decision_pass(decision), decision)

        event = build_lifecycle_control_event(
            request,
            event_id="event-1",
            event_type="post-action",
            status="PASS",
            producer_id="host-hook",
            outcome={"changed": False},
        )
        self.assertEqual(validate_lifecycle_control_event(event)["status"], "PASS")
        self.assertIs(require_lifecycle_control_event_pass(event), event)
        policy = build_default_lifecycle_control_policy()
        self.assertEqual(validate_lifecycle_control_request_with_policy(request, policy)["status"], "PASS")
        self.assertEqual(validate_lifecycle_control_decision_with_policy(decision, policy)["status"], "PASS")
        self.assertEqual(validate_lifecycle_control_event_with_policy(event, policy)["status"], "PASS")
        self.assertEqual(validate_lifecycle_control_event_batch_with_policy([event], policy)["status"], "PASS")
        now = datetime.now(UTC).replace(microsecond=0)
        attestation = build_lifecycle_control_attestation(
            attestation_id="attestation-1",
            producer_id="host-hook",
            adapter_id="example",
            host_version="1.2.3",
            operation="file-edit",
            nonce="0123456789abcdef",
            issued_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            plan_digest="a" * 64,
            lock_digest="b" * 64,
            state_revision=1,
            action_digest="c" * 64,
            outcome_digest="d" * 64,
            key_id="external-key-1",
            signature="signature",
        )
        self.assertEqual(validate_lifecycle_control_attestation_with_policy(attestation, policy)["status"], "PASS")
        receipt = build_lifecycle_control_qualification_receipt(
            adapter_id="example",
            host="example-host",
            host_version="1.2.3",
            operation="file-edit",
            declared_level="GUIDANCE_ONLY",
            supported_level="GUIDANCE_ONLY",
            qualified_level="OFF",
            status="UNAVAILABLE",
            positive_evidence=[],
            negative_evidence=[],
            evidence_refs=["work/qualification.json"],
        )
        self.assertEqual(validate_lifecycle_control_qualification_with_policy(receipt, policy)["status"], "PASS")

    def test_invalid_policy_has_stable_failure(self) -> None:
        validation = validate_lifecycle_control_policy({})

        with self.assertRaisesRegex(Exception, "policy"):
            require_lifecycle_control_policy_pass(validation)


if __name__ == "__main__":
    unittest.main()
