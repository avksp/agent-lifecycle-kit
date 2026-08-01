from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.runner import (
    build_credential_proxy_details,
    build_partial_process_boundary,
    build_sandbox_receipt,
    build_unknown_sandbox_capability,
    require_sandbox_receipt_pass,
    validate_sandbox_capability,
    validate_sandbox_receipt,
)


class SandboxReceiptTests(unittest.TestCase):
    def test_pass_receipt_covers_all_runtime_boundaries(self) -> None:
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS20-02",
            attempt=1,
            boundaries=_enforced_boundaries(),
            enforcement={"source": "HOST", "verified": True, "evidenceIds": ["ev-host-sandbox"], "details": {}},
            verifier={"tool": "unit-test"},
            evidence_ids=["ev-host-sandbox"],
        )

        validation = validate_sandbox_receipt(receipt, expected_lineage=_lineage(), task_id="WS20-02", attempt=1)

        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["sandboxStatus"], "PASS")
        self.assertEqual(validation["unknownBoundaryCount"], 0)
        self.assertTrue(receipt["writeScopeBoundary"]["gitWriteScopeGovernedSeparately"])
        self.assertFalse(receipt["productionPromotionClaimed"])

    def test_unknown_receipt_is_valid_but_not_required_pass(self) -> None:
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS20-02",
            attempt=1,
            boundaries=_unknown_boundaries(),
            enforcement={"source": "UNKNOWN", "verified": False, "evidenceIds": [], "details": {}},
            verifier={"tool": "unit-test"},
        )

        validation = validate_sandbox_receipt(receipt)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["sandboxStatus"], "UNKNOWN")
        self.assertEqual(validation["unknownBoundaryCount"], 4)
        with self.assertRaises(LifecycleError):
            require_sandbox_receipt_pass(validation)

    def test_pass_receipt_cannot_overclaim_unknown_boundaries(self) -> None:
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS20-02",
            attempt=1,
            boundaries=_unknown_boundaries(),
            enforcement={"source": "UNKNOWN", "verified": False, "evidenceIds": [], "details": {}},
            verifier={"tool": "unit-test"},
            status="PASS",
        )

        validation = validate_sandbox_receipt(receipt)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("sandbox-pass-overclaims-unknown-boundary", codes)
        self.assertIn("sandbox-pass-overclaims-enforcement-source", codes)

    def test_unknown_adapter_capability_is_explicit_without_overclaim(self) -> None:
        capability = build_unknown_sandbox_capability()

        validation = validate_sandbox_capability(capability)

        self.assertEqual(capability["status"], "UNKNOWN")
        self.assertFalse(capability["verified"])
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["unknownBoundaryCount"], 4)

    def test_partial_process_containment_is_valid_but_not_required_pass(self) -> None:
        boundaries = _enforced_boundaries()
        boundaries["process"] = build_partial_process_boundary(
            evidence_ids=["ev-process-partial"],
            covered=["direct-child-process"],
            limitations=["windows-process-tree-grandchildren-not-guaranteed"],
            platforms=["windows"],
        )
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS32-02",
            attempt=1,
            boundaries=boundaries,
            enforcement={"source": "HOST", "verified": True, "evidenceIds": ["ev-process-partial"], "details": {}},
            verifier={"tool": "unit-test"},
            evidence_ids=["ev-process-partial"],
        )

        validation = validate_sandbox_receipt(receipt)

        self.assertEqual(receipt["status"], "UNKNOWN")
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["sandboxStatus"], "UNKNOWN")
        self.assertEqual(validation["partialBoundaryCount"], 1)

    def test_pass_receipt_cannot_overclaim_partial_containment(self) -> None:
        boundaries = _enforced_boundaries()
        boundaries["process"] = build_partial_process_boundary(
            evidence_ids=["ev-process-partial"],
            covered=["direct-child-process"],
            limitations=["process-tree-coverage-is-partial"],
        )
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS32-02",
            attempt=1,
            boundaries=boundaries,
            enforcement={"source": "HOST", "verified": True, "evidenceIds": ["ev-process-partial"], "details": {}},
            verifier={"tool": "unit-test"},
            status="PASS",
        )

        validation = validate_sandbox_receipt(receipt)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("sandbox-pass-overclaims-partial-boundary", {item["code"] for item in validation["blockers"]})

    def test_credential_proxy_boundary_requires_redacted_placeholder(self) -> None:
        boundaries = _enforced_boundaries()
        boundaries["environment"]["details"] = build_credential_proxy_details(
            source="HOST_ENV",
            attachment="host-harness-env-injection",
            egress_boundary="host-process-only",
            allowed_env_names=["PROVIDER_API_KEY"],
        )
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS32-02",
            attempt=1,
            boundaries=boundaries,
            enforcement={"source": "HOST", "verified": True, "evidenceIds": ["ev-credential-proxy"], "details": {}},
            verifier={"tool": "unit-test"},
            evidence_ids=["ev-credential-proxy"],
        )

        validation = validate_sandbox_receipt(receipt)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["credentialProxyCount"], 1)
        self.assertTrue(validation["credentialProxyRedacted"])

    def test_credential_proxy_boundary_rejects_secret_values(self) -> None:
        boundaries = _enforced_boundaries()
        boundaries["environment"]["details"] = {
            "credentialProxy": {
                "source": "HOST_ENV",
                "attachment": "host-harness-env-injection",
                "egressBoundary": "host-process-only",
                "allowedEnvNames": ["PROVIDER_API_KEY"],
                "sandboxCredentialValue": "not-redacted-credential-value",
                "secretValueStoredInReceipt": True,
            }
        }
        receipt = build_sandbox_receipt(
            lineage=_lineage(),
            task_id="WS32-02",
            attempt=1,
            boundaries=boundaries,
            enforcement={"source": "HOST", "verified": True, "evidenceIds": ["ev-credential-proxy"], "details": {}},
            verifier={"tool": "unit-test"},
        )

        validation = validate_sandbox_receipt(receipt)

        codes = {item["code"] for item in validation["blockers"]}
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("sandbox-credential-proxy-secret-stored", codes)
        self.assertIn("sandbox-credential-proxy-secret-value", codes)


def _lineage() -> dict:
    return {
        "runId": "run-1",
        "packageId": "release-1-10",
        "planRevision": 4,
        "planDigest": "a" * 64,
        "sourceRevision": "b" * 40,
    }


def _enforced_boundaries() -> dict:
    return {
        name: {"mode": "ENFORCED", "evidenceIds": [f"ev-{name}"], "details": {}}
        for name in ("filesystem", "network", "process", "environment")
    }


def _unknown_boundaries() -> dict:
    return {
        name: {"mode": "UNKNOWN", "evidenceIds": [], "details": {}}
        for name in ("filesystem", "network", "process", "environment")
    }


if __name__ == "__main__":
    unittest.main()
