from __future__ import annotations

import unittest

from agent_lifecycle.host_protocol import (
    build_acp_capability,
    build_acp_probe_receipt,
    validate_host_capabilities,
    validate_no_acp_evidence_for_hosts,
)


class AcpCapabilityTests(unittest.TestCase):
    def test_supported_acp_capability_is_neutral_and_schema_backed(self) -> None:
        capability = build_acp_capability(adapter_id="goose", host="goose", support="supported", probe_command=["goose", "--help"])

        validation = validate_host_capabilities([capability], adapter_id="goose", host="goose")

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(capability["providerIdentityUsed"])
        self.assertEqual(capability["capabilityId"], "acp")
        self.assertEqual(capability["invocationContract"]["unsupportedOperationPolicy"], "fail-closed")

    def test_provider_identity_claim_fails_validation(self) -> None:
        capability = build_acp_capability(adapter_id="goose", host="goose", support="supported")
        capability["providerIdentityUsed"] = True

        validation = validate_host_capabilities([capability], adapter_id="goose", host="goose")

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("host-capability-provider-identity", {item["code"] for item in validation["blockers"]})

    def test_supported_acp_probe_receipt_fails_closed(self) -> None:
        capability = build_acp_capability(adapter_id="goose", host="goose", support="supported")

        receipt = build_acp_probe_receipt(
            capability,
            executable_found=False,
            probe_passed=False,
            invocation_contract_valid=False,
        )

        self.assertEqual(receipt["status"], "FAIL")
        self.assertFalse(receipt["liveCallsStarted"])
        self.assertIn("acp-executable-missing", {item["code"] for item in receipt["blockers"]})
        self.assertIn("acp-probe-failed", {item["code"] for item in receipt["blockers"]})
        self.assertIn("acp-invocation-contract-invalid", {item["code"] for item in receipt["blockers"]})

    def test_excluded_hosts_have_no_positive_capability_evidence(self) -> None:
        capability = build_acp_capability(adapter_id="blocked", host="blocked-host", support="supported")

        validation = validate_no_acp_evidence_for_hosts([capability], excluded_hosts={"blocked-host"})

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("excluded-host-acp-evidence", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
