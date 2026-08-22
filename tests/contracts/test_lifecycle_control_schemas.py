from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    CONTROL_LEVELS,
    CONTROL_OPERATIONS,
    LIFECYCLE_CONTROL_SCHEMAS,
    build_default_lifecycle_control_policy,
    build_lifecycle_control_attestation,
    build_lifecycle_control_decision,
    build_lifecycle_control_event,
    build_lifecycle_control_qualification_receipt,
    build_lifecycle_control_request,
    lifecycle_control_limits,
    resolve_lifecycle_control,
    validate_lifecycle_control_attestation,
    validate_lifecycle_control_decision,
    validate_lifecycle_control_event,
    validate_lifecycle_control_event_batch,
    validate_lifecycle_control_policy,
    validate_lifecycle_control_qualification_receipt,
    validate_lifecycle_control_request,
)
from agent_lifecycle.contracts.schemas import get_schema, list_schemas


def _request() -> dict:
    return build_lifecycle_control_request(
        request_id="request-1",
        adapter_id="example",
        host="example-host",
        host_version="1.2.3",
        operation="file-edit",
        run_id="run-1",
        task_id="WS80-01",
        package_id="release-1-80",
        plan_revision=5,
        plan_digest="a" * 64,
        lock_digest="b" * 64,
        state_revision=4,
        action_digest="c" * 64,
        paths=["src/example.py"],
        nonce="0123456789abcdef",
    )


class LifecycleControlSchemaTests(unittest.TestCase):
    def test_schema_group_is_registered_and_closed_at_request_boundary(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertTrue(set(LIFECYCLE_CONTROL_SCHEMAS).issubset(schema_ids))
        self.assertFalse(get_schema("agent-lifecycle-control-request.v1")["additionalProperties"])
        self.assertEqual(CONTROL_LEVELS[-1], "ENFORCED")

    def test_default_policy_is_guidance_only_and_valid(self) -> None:
        policy = build_default_lifecycle_control_policy()

        self.assertEqual(validate_lifecycle_control_policy(policy)["status"], "PASS")
        self.assertEqual(policy["defaultLevel"], "GUIDANCE_ONLY")
        self.assertTrue(all(item["effectiveLevel"] == "GUIDANCE_ONLY" for item in policy["operations"].values()))

    def test_policy_cannot_escalate_without_support_and_qualification(self) -> None:
        policy = build_default_lifecycle_control_policy()
        policy["operations"]["file-edit"]["effectiveLevel"] = "ENFORCED"
        policy["policyDigest"] = canonical_digest(
            {key: value for key, value in policy.items() if key != "policyDigest"}
        )

        validation = validate_lifecycle_control_policy(policy)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("control-policy-unqualified-enforced", {item["code"] for item in validation["blockers"]})

        unknown = build_default_lifecycle_control_policy()
        unknown["authority"]["modelWritableByPrompt"] = True
        unknown["policyDigest"] = canonical_digest(
            {key: value for key, value in unknown.items() if key != "policyDigest"}
        )
        unknown_validation = validate_lifecycle_control_policy(unknown)
        self.assertEqual(unknown_validation["status"], "FAIL")
        self.assertIn(
            "control-policy-authority-unknown-field", {item["code"] for item in unknown_validation["blockers"]}
        )

    def test_request_rejects_prompt_and_unsafe_path(self) -> None:
        request = _request()
        request["prompt"] = "untrusted text"
        request["requestDigest"] = canonical_digest(
            {key: value for key, value in request.items() if key != "requestDigest"}
        )

        validation = validate_lifecycle_control_request(request)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("control-untrusted-field", {item["code"] for item in validation["blockers"]})

        unsafe = _request()
        unsafe["paths"] = ["../outside"]
        unsafe["requestDigest"] = canonical_digest(
            {key: value for key, value in unsafe.items() if key != "requestDigest"}
        )
        self.assertEqual(validate_lifecycle_control_request(unsafe)["status"], "FAIL")

        unknown = _request()
        unknown["authority"] = {"modelWritable": True}
        unknown["requestDigest"] = canonical_digest(
            {key: value for key, value in unknown.items() if key != "requestDigest"}
        )
        unknown_validation = validate_lifecycle_control_request(unknown)
        self.assertEqual(unknown_validation["status"], "FAIL")
        self.assertIn("control-request-unknown-field", {item["code"] for item in unknown_validation["blockers"]})

    def test_event_redacts_untrusted_outcome_and_binds_request(self) -> None:
        event = build_lifecycle_control_event(
            _request(),
            event_id="event-1",
            event_type="post-action",
            status="PASS",
            producer_id="host-hook",
            outcome={"changed": True, "environment": {"TOKEN": "secret"}},
            changed_paths=["src/example.py"],
        )

        self.assertEqual(event["outcome"]["environment"], "<redacted>")
        self.assertEqual(validate_lifecycle_control_event(event)["status"], "PASS")
        event["outcome"]["changed"] = False
        self.assertEqual(validate_lifecycle_control_event(event)["status"], "FAIL")

    def test_attestation_is_domain_separated_and_time_bounded(self) -> None:
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
            state_revision=4,
            action_digest="c" * 64,
            outcome_digest="d" * 64,
            key_id="external-key-1",
            signature="signature",
        )

        self.assertEqual(validate_lifecycle_control_attestation(attestation, reference_time=now)["status"], "PASS")
        attestation["domain"] = "wrong-domain"
        self.assertEqual(validate_lifecycle_control_attestation(attestation, reference_time=now)["status"], "FAIL")

        malformed = build_lifecycle_control_attestation(
            attestation_id="attestation-malformed",
            producer_id="host-hook",
            adapter_id="example",
            host_version="1.2.3",
            operation="file-edit",
            nonce="0123456789abcdef",
            issued_at="2026-08-22T00:00:00",
            expires_at="2026-08-22T00:05:00Z",
            plan_digest="a" * 64,
            lock_digest="b" * 64,
            state_revision=4,
            action_digest="c" * 64,
            outcome_digest="d" * 64,
            key_id="external-key-1",
            signature="signature",
        )
        self.assertEqual(validate_lifecycle_control_attestation(malformed, reference_time=now)["status"], "FAIL")

        expired = dict(attestation)
        expired["domain"] = "agent-lifecycle-control-attestation.v1"
        expired["issuedAt"] = (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        expired["expiresAt"] = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        expired["attestationDigest"] = canonical_digest(
            {key: value for key, value in expired.items() if key != "attestationDigest"}
        )
        expired_validation = validate_lifecycle_control_attestation(expired, reference_time=now)
        self.assertEqual(expired_validation["status"], "FAIL")
        self.assertIn("control-attestation-expired", {item["code"] for item in expired_validation["blockers"]})

    def test_policy_resolution_is_fail_closed_for_all_levels_and_operations(self) -> None:
        policy = build_default_lifecycle_control_policy()

        for operation in CONTROL_OPERATIONS:
            for requested_level in CONTROL_LEVELS:
                decision = resolve_lifecycle_control(policy, operation, requested_level=requested_level)
                self.assertEqual(decision["effectiveLevel"], "GUIDANCE_ONLY")
                expected_status = "PASS" if requested_level in {"OFF", "GUIDANCE_ONLY"} else "REVIEW_REQUIRED"
                self.assertEqual(decision["status"], expected_status)

        invalid = dict(policy)
        invalid["limits"] = {**policy["limits"], "maxEvents": 0}
        invalid["policyDigest"] = canonical_digest(
            {key: value for key, value in invalid.items() if key != "policyDigest"}
        )
        invalid_decision = resolve_lifecycle_control(invalid, "file-edit")
        self.assertEqual(invalid_decision["status"], "REVIEW_REQUIRED")
        self.assertEqual(invalid_decision["effectiveLevel"], "GUIDANCE_ONLY")

        for malformed in (None, [], "policy", 42, True):
            resolved = resolve_lifecycle_control(malformed, "file-edit")
            self.assertEqual(resolved["status"], "REVIEW_REQUIRED")
            self.assertEqual(resolved["effectiveLevel"], "GUIDANCE_ONLY")

    def test_decision_validator_checks_builder_output(self) -> None:
        decision = build_lifecycle_control_decision(
            _request(),
            status="PASS",
            effective_level="GUIDANCE_ONLY",
            host_action_allowed=False,
        )

        self.assertEqual(validate_lifecycle_control_decision(decision)["status"], "PASS")
        decision["authority"] = "model"
        decision["decisionDigest"] = canonical_digest(
            {key: value for key, value in decision.items() if key != "decisionDigest"}
        )
        self.assertEqual(validate_lifecycle_control_decision(decision)["status"], "FAIL")

    def test_policy_limits_apply_to_requests_events_and_event_batches(self) -> None:
        policy = build_default_lifecycle_control_policy()
        policy["limits"].update({"maxEvents": 1, "maxPayloadBytes": 512, "maxChangedPaths": 1, "maxNonceBytes": 16})
        policy["policyDigest"] = canonical_digest(
            {key: value for key, value in policy.items() if key != "policyDigest"}
        )
        limits = lifecycle_control_limits(policy)
        self.assertEqual(limits["maxEvents"], 1)

        request = _request()
        request["paths"] = ["src/example.py", "src/other.py"]
        request["requestDigest"] = canonical_digest(
            {key: value for key, value in request.items() if key != "requestDigest"}
        )
        self.assertEqual(validate_lifecycle_control_request(request, policy_limits=limits)["status"], "FAIL")

        event = build_lifecycle_control_event(
            _request(),
            event_id="event-large",
            event_type="post-action",
            status="PASS",
            producer_id="host-hook",
            outcome={"message": "x" * 600},
        )
        self.assertEqual(validate_lifecycle_control_event(event, policy_limits=limits)["status"], "FAIL")
        self.assertEqual(validate_lifecycle_control_event_batch([event, event], policy_limits=limits)["status"], "FAIL")

    def test_decision_and_redaction_boundaries_reject_deep_and_raw_values(self) -> None:
        decision = build_lifecycle_control_decision(
            _request(),
            status="PASS",
            effective_level="GUIDANCE_ONLY",
            host_action_allowed=False,
        )
        nested: dict[str, object] = {"leaf": "value"}
        for _ in range(130):
            nested = {"nested": nested}
        decision["blockers"] = [nested]
        decision["decisionDigest"] = canonical_digest(
            {key: value for key, value in decision.items() if key != "decisionDigest"}
        )
        self.assertEqual(validate_lifecycle_control_decision(decision)["status"], "FAIL")

        event = build_lifecycle_control_event(
            _request(),
            event_id="event-raw",
            event_type="post-action",
            status="PASS",
            producer_id="host-hook",
            outcome={"changed": True},
        )
        event["outcome"] = {42: "value", "child_api_key": "sk-proj-raw-secret-value-1234567890"}
        event["eventDigest"] = "0" * 64
        self.assertEqual(validate_lifecycle_control_event(event)["status"], "FAIL")
        with self.assertRaises(LifecycleError):
            build_lifecycle_control_event(
                _request(),
                event_id="event-invalid-builder",
                event_type="post-action",
                status="PASS",
                producer_id="host-hook",
                outcome={42: "value"},
            )

        policy = build_default_lifecycle_control_policy()
        policy["policyId"] = "p" * 129
        policy["policyDigest"] = canonical_digest(
            {key: value for key, value in policy.items() if key != "policyDigest"}
        )
        self.assertEqual(validate_lifecycle_control_policy(policy)["status"], "FAIL")

    def test_enforced_qualification_requires_negative_evidence(self) -> None:
        receipt = build_lifecycle_control_qualification_receipt(
            adapter_id="example",
            host="example-host",
            host_version="1.2.3",
            operation="file-edit",
            declared_level="ENFORCED",
            supported_level="ENFORCED",
            qualified_level="ENFORCED",
            status="QUALIFIED",
            positive_evidence=[{"id": "positive"}],
            negative_evidence=[],
            evidence_refs=["work/qualification.json"],
        )

        validation = validate_lifecycle_control_qualification_receipt(receipt)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "control-qualification-negative-evidence-required", {item["code"] for item in validation["blockers"]}
        )


if __name__ == "__main__":
    unittest.main()
