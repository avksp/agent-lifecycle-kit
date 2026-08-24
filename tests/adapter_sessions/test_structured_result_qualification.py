from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.qualification import (
    build_structured_result_qualification_receipt,
    validate_structured_result_qualification_receipt,
)


class StructuredResultQualificationTests(unittest.TestCase):
    def test_receipt_binds_operation_and_is_advisory(self) -> None:
        receipt = _receipt()

        validation = validate_structured_result_qualification_receipt(
            receipt,
            expected={"planDigest": "e" * 64, "lockDigest": "f" * 64},
        )

        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(receipt["advisoryOnly"])
        self.assertFalse(receipt["automaticRouteAdoptionEligible"])

    def test_lineage_mutation_fails_closed(self) -> None:
        receipt = _receipt()
        receipt["planDigest"] = "0" * 64

        validation = validate_structured_result_qualification_receipt(
            receipt,
            expected={"planDigest": "e" * 64, "lockDigest": "f" * 64},
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("structured-result-qualification-lineage", {item["code"] for item in validation["blockers"]})


def _receipt() -> dict:
    return build_structured_result_qualification_receipt(
        operation_id="reference-evaluation",
        adapter_id="test-adapter",
        descriptor_digest="a" * 64,
        host_version="1.0.0",
        model_class="small",
        required_mode="JSON_ENFORCED",
        required_schema_digest="b" * 64,
        capability_manifest_digest="c" * 64,
        capability_level="SCHEMA_ENFORCED",
        evidence_digest="d" * 64,
        measured_run_count=10,
        plan_digest="e" * 64,
        lock_digest="f" * 64,
    )


if __name__ == "__main__":
    unittest.main()
