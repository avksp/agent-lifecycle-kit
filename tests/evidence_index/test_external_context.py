from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.evidence_index import (
    build_external_context_import_receipt,
    external_context_hints_from_receipts,
    require_external_context_import_pass,
    validate_external_context_import_receipt,
)


class ExternalContextImportTests(unittest.TestCase):
    def test_external_context_receipt_is_optional_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "memory.md"
            source.write_text("Prior analysis says payment retries need idempotency keys.", encoding="utf-8")

            receipt = build_external_context_import_receipt(
                source, citation="operator export", source_id="memory-export"
            )
            validation = validate_external_context_import_receipt(receipt)

            self.assertEqual(require_external_context_import_pass(validation)["status"], "PASS")
            self.assertEqual(receipt["schemaVersion"], "agent-external-context-import-receipt.v1")
            self.assertFalse(receipt["sourceOfTruth"])
            self.assertFalse(receipt["enabledByDefault"])
            self.assertFalse(receipt["rawContentStored"])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertFalse(receipt["networkCallsStarted"])
            self.assertEqual(receipt["hints"][0]["contextRole"], "optional-external-context")
            self.assertFalse(receipt["hints"][0]["proof"])

    def test_external_context_redacts_secret_like_values_and_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "memory.md"
            source.write_text(
                "Use API_KEY=secret-value from " + "/" + "Users/local/private-note only as context.",
                encoding="utf-8",
            )

            receipt = build_external_context_import_receipt(source, citation="/" + "Users/local/private-citation")
            rendered = str(receipt)

            self.assertEqual(validate_external_context_import_receipt(receipt)["status"], "PASS")
            self.assertEqual(receipt["redaction"]["status"], "REDACTED")
            self.assertNotIn("secret-value", rendered)
            self.assertNotIn("/" + "Users/local", rendered)
            self.assertIn("[REDACTED]", receipt["hints"][0]["text"])
            self.assertIn("[LOCAL_PATH]", receipt["hints"][0]["text"])

    def test_partial_bearer_markers_are_sanitized_once_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "memory.md"
            for value in ("[REDACTED]suffix", "prefix[REDACTED]", "[REDACTED][REDACTED]"):
                with self.subTest(value=value):
                    source.write_text("Bearer " + value, encoding="utf-8")
                    receipt = build_external_context_import_receipt(source)
                    self.assertEqual(receipt["hints"][0]["text"], "Bearer [REDACTED]")
                    self.assertEqual(receipt["redaction"]["status"], "REDACTED")
                    self.assertEqual(validate_external_context_import_receipt(receipt)["status"], "PASS")
            source.write_text("Bearer [REDACTED]", encoding="utf-8")
            receipt = build_external_context_import_receipt(source)
            self.assertEqual(receipt["hints"][0]["text"], "Bearer [REDACTED]")
            self.assertEqual(validate_external_context_import_receipt(receipt)["status"], "PASS")

    def test_external_context_normalizes_public_url_citation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "memory.md"
            source.write_text("Public reference", encoding="utf-8")

            receipt = build_external_context_import_receipt(
                source,
                citation="HTTPS://EXAMPLE.COM:443/reference#Public",
            )

            self.assertEqual(receipt["source"]["citation"], "https://example.com/reference#Public")
            self.assertEqual(receipt["hints"][0]["citation"], receipt["source"]["citation"])
            self.assertEqual(validate_external_context_import_receipt(receipt)["status"], "PASS")

    def test_external_context_rejects_raw_and_partial_redaction_even_with_valid_digest(self) -> None:
        cases = (
            ("API_KEY=secret-value", "external-context-secret-leakage"),
            ("API_KEY=[REDACTED]suffix", "external-context-secret-leakage"),
            ("API_KEY=prefix[REDACTED]", "external-context-secret-leakage"),
            ("Bearer [REDACTED]suffix", "external-context-secret-leakage"),
            ("Bearer prefix[REDACTED]", "external-context-secret-leakage"),
            ("Bearer [REDACTED][REDACTED]", "external-context-secret-leakage"),
            ("/" + "Users/local/private-note", "external-context-private-path-leakage"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "memory.md"
            source.write_text("Safe optional context.", encoding="utf-8")
            for text, expected in cases:
                with self.subTest(text=text):
                    receipt = build_external_context_import_receipt(source)
                    receipt["hints"][0]["text"] = text
                    receipt["receiptDigest"] = canonical_digest(
                        {key: value for key, value in receipt.items() if key != "receiptDigest"}
                    )
                    result = validate_external_context_import_receipt(receipt)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertIn(expected, {row["code"] for row in result["blockers"]})
                    self.assertNotIn("external-context-digest-mismatch", {row["code"] for row in result["blockers"]})

    def test_external_context_hints_require_valid_non_proof_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "memory.md"
            source.write_text("Architecture note: prefer explicit lifecycle receipts.", encoding="utf-8")
            receipt = build_external_context_import_receipt(source)

            hints = external_context_hints_from_receipts([receipt])
            invalid = {**receipt, "sourceOfTruth": True}

            self.assertEqual(hints[0]["contextRole"], "optional-external-context")
            with self.assertRaises(LifecycleError):
                external_context_hints_from_receipts([invalid])


if __name__ == "__main__":
    unittest.main()
