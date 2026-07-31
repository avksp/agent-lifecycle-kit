from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.runner import (
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
