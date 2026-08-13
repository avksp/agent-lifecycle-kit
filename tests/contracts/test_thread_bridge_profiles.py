from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.thread_bridge_schemas import (
    build_thread_bridge_profile,
    build_thread_bridge_qualification_receipt,
    resolve_thread_operation_status,
    validate_thread_bridge_profile,
    validate_thread_bridge_qualification_receipt,
)
from agent_lifecycle.policy.thread_bridge import build_default_thread_bridge_policy, evaluate_thread_operation


def _profile(status: str = "WRAPPER_ONLY") -> dict:
    return build_thread_bridge_profile(
        adapter_id="example",
        host="example-host",
        descriptor_digest="a" * 64,
        capability_manifest_digest="b" * 64,
        host_range={"minimumVersion": "1.0", "maximumVersion": "1.0"},
        operations=[
            {"name": "read", "declaredStatus": status},
            {"name": "list", "declaredStatus": "UNSUPPORTED"},
            {"name": "send", "declaredStatus": "UNSUPPORTED"},
            {"name": "create", "declaredStatus": "UNSUPPORTED"},
        ],
    )


class ThreadBridgeProfileContractTests(unittest.TestCase):
    def test_profile_is_additive_and_validated(self) -> None:
        profile = _profile()

        self.assertEqual(validate_thread_bridge_profile(profile)["status"], "PASS")
        self.assertEqual(profile["policyVersion"], "agent-thread-bridge-policy.v1")
        self.assertTrue(profile["qualificationRequired"])
        self.assertFalse(profile["providerIdentityUsed"])

    def test_declaration_without_receipt_never_becomes_supported(self) -> None:
        decision = resolve_thread_operation_status(_profile(), "read")

        self.assertEqual(decision["declaredStatus"], "WRAPPER_ONLY")
        self.assertEqual(decision["qualificationStatus"], "UNQUALIFIED")
        self.assertEqual(decision["capabilitySupport"], "unknown")
        self.assertNotEqual(decision["effectiveStatus"], "SUPPORTED")

    def test_matching_receipt_projects_to_existing_supported_value(self) -> None:
        profile = _profile()
        receipt = build_thread_bridge_qualification_receipt(
            receipt_id="qualification-1",
            adapter_id=profile["adapterId"],
            host=profile["host"],
            descriptor_digest=profile["descriptorDigest"],
            capability_manifest_digest=profile["capabilityManifestDigest"],
            host_range=profile["hostRange"],
            operation_set=["read"],
            evidence_refs=["work/qualification.json"],
        )

        self.assertEqual(validate_thread_bridge_qualification_receipt(receipt)["status"], "PASS")
        decision = resolve_thread_operation_status(profile, "read", qualification_receipt=receipt)
        self.assertEqual(decision["qualificationStatus"], "QUALIFIED")
        self.assertEqual(decision["effectiveStatus"], "SUPPORTED")
        self.assertEqual(decision["capabilitySupport"], "supported")

    def test_receipt_for_different_descriptor_fails_closed(self) -> None:
        profile = _profile()
        receipt = build_thread_bridge_qualification_receipt(
            receipt_id="qualification-2",
            adapter_id=profile["adapterId"],
            host=profile["host"],
            descriptor_digest="c" * 64,
            capability_manifest_digest=profile["capabilityManifestDigest"],
            host_range=profile["hostRange"],
            operation_set=["read"],
            evidence_refs=["work/qualification.json"],
        )

        decision = resolve_thread_operation_status(profile, "read", qualification_receipt=receipt)
        self.assertEqual(decision["qualificationStatus"], "STALE")
        self.assertEqual(decision["capabilitySupport"], "unknown")
        self.assertIn("thread-qualification-binding-mismatch", {item["code"] for item in decision["blockers"]})

    def test_invalid_status_is_rejected(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "status"):
            _profile("supported")

    def test_projection_does_not_override_disabled_policy(self) -> None:
        policy = build_default_thread_bridge_policy()
        policy["mode"] = "controlled"
        policy["operations"]["read"]["enabled"] = True
        wrapper = evaluate_thread_operation(policy, "read", capability_support="unknown")
        supported = evaluate_thread_operation(policy, "read", capability_support="supported")
        disabled = evaluate_thread_operation(build_default_thread_bridge_policy(), "read", capability_support="supported")

        self.assertNotEqual(wrapper["status"], "PASS")
        self.assertEqual(supported["status"], "PASS")
        self.assertNotEqual(disabled["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
