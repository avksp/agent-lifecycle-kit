from __future__ import annotations

import unittest

from agent_lifecycle.quality import (
    build_failure_classification_receipt,
    validate_failure_classification_receipt,
)


class FailureClassificationTests(unittest.TestCase):
    def test_classifies_required_failure_fixtures(self) -> None:
        cases = [
            ("edge-case", {"exceptionType": "IndexError", "logPattern": "empty input boundary out of range"}),
            ("api-contract", {"exceptionType": "AssertionError", "failingAssertion": "expected HTTP status code 404"}),
            ("race", {"logPattern": "race detected in concurrent async ordering"}),
            ("flaky-test", {"logPattern": "test is intermittent and passes on retry"}),
            ("security-bug", {"logPattern": "security vulnerability token leak"}),
            ("unknown", {"logPattern": "plain failure with no known pattern"}),
        ]

        for expected_class, failure in cases:
            with self.subTest(expected_class=expected_class):
                receipt = build_failure_classification_receipt(failure=failure, evidence_ids=["EV39-CLASSIFIER"])
                validation = validate_failure_classification_receipt(receipt)

                self.assertEqual(receipt["schemaVersion"], "agent-failure-classification-receipt.v1")
                self.assertEqual(receipt["failureClass"], expected_class)
                self.assertEqual(validation["status"], "PASS")
                self.assertTrue(receipt["evidence"]["evidenceBacked"])
                if expected_class == "unknown":
                    self.assertEqual(receipt["confidence"], "LOW")

    def test_flake_signal_overrides_generic_failure_text(self) -> None:
        receipt = build_failure_classification_receipt(
            failure={"logPattern": "validation assertion changed"},
            flake_signal={"status": "flaky", "runs": 5, "failures": 2},
        )

        self.assertEqual(receipt["failureClass"], "flaky-test")
        self.assertEqual(receipt["confidence"], "HIGH")
        self.assertEqual(validate_failure_classification_receipt(receipt)["status"], "PASS")

    def test_provider_model_keys_fail_closed(self) -> None:
        receipt = build_failure_classification_receipt(
            failure={"logPattern": "security vulnerability", "providerModel": "host-specific"},
        )
        validation = validate_failure_classification_receipt(receipt)

        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(validation["status"], "PASS")
        self.assertIn("failure-classification-provider-model-key", {item["code"] for item in receipt["blockers"]})


if __name__ == "__main__":
    unittest.main()
