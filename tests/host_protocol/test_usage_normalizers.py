from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, canonical_digest  # noqa: E402
from agent_lifecycle.host_protocol import (  # noqa: E402
    NormalizedUsage,
    build_conservative_usage_estimate,
    build_model_usage_sidecar,
    parse_bounded_jsonl_objects,
    validate_usage_normalization_profile,
)


class UsageNormalizerContractTests(unittest.TestCase):
    def test_deep_json_is_rejected_with_a_lifecycle_error(self) -> None:
        source = b'{"nested":' + (b"[" * 5_000) + b"0" + (b"]" * 5_000) + b"}\n"

        with self.assertRaises(LifecycleError) as raised:
            parse_bounded_jsonl_objects(source)

        self.assertEqual(raised.exception.code, "usage-event-depth-exceeded")

    def test_qualified_host_sidecar_is_path_free_and_attested(self) -> None:
        receipt = build_model_usage_sidecar(
            usage=NormalizedUsage(input_tokens=100, output_tokens=20, billable_tokens=120, tool_calls=2),
            operation_id="op-1",
            adapter_id="qwen-code",
            host="qwen-code",
            model_class="standard-code",
            provider_model_hash="a" * 64,
            route_decision_digest="b" * 64,
            source_bytes=b'{"usage":{"inputTokens":100}}\n',
            source_format="stream-jsonl",
            source_kind="host",
            normalizer_status="QUALIFIED",
            normalizer_digest="c" * 64,
        )

        self.assertEqual(receipt["attestation"]["status"], "ATTESTED")
        self.assertTrue(receipt["attestation"]["acceptedForS1S2"])
        self.assertNotIn("path", receipt["sourceArtifact"])
        self.assertEqual(
            receipt["receiptDigest"],
            canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"}),
        )

    def test_fixture_sidecar_never_claims_attestation(self) -> None:
        receipt = build_model_usage_sidecar(
            usage=NormalizedUsage(input_tokens=10, output_tokens=5, billable_tokens=15),
            operation_id="op-2",
            adapter_id="gemini-cli",
            host="gemini-cli",
            model_class="standard-code",
            provider_model_hash="a" * 64,
            route_decision_digest="b" * 64,
            source_bytes=b"{}\n",
            source_format="stream-jsonl",
            source_kind="fixture",
            normalizer_status="FIXTURE_ONLY",
            normalizer_digest="c" * 64,
        )

        self.assertEqual(receipt["attestation"]["status"], "ESTIMATED")
        self.assertFalse(receipt["attestation"]["acceptedForS1S2"])
        self.assertFalse(receipt["normalizer"]["acceptedForS1S2"])

    def test_core_fallback_is_conservative_and_visible(self) -> None:
        source = b"abc def"
        receipt = build_conservative_usage_estimate(
            operation_id="op-3",
            adapter_id="unknown-adapter",
            host="unknown-host",
            model_class="standard-code",
            provider_model_hash="a" * 64,
            route_decision_digest="b" * 64,
            source_bytes=source,
        )

        self.assertEqual(receipt["usage"]["billableTokens"], len(source))
        self.assertEqual(receipt["attestation"]["source"], "core-estimate")
        self.assertEqual(receipt["attestation"]["status"], "ESTIMATED")
        self.assertEqual(receipt["normalizer"]["status"], "UNSUPPORTED")

    def test_qualified_fixture_source_is_rejected(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            build_model_usage_sidecar(
                usage=NormalizedUsage(input_tokens=1),
                operation_id="op-4",
                adapter_id="qwen-code",
                host="qwen-code",
                model_class="standard-code",
                provider_model_hash="a" * 64,
                route_decision_digest="b" * 64,
                source_bytes=b"{}\n",
                source_format="stream-jsonl",
                source_kind="fixture",
                normalizer_status="QUALIFIED",
                normalizer_digest="c" * 64,
            )

        self.assertEqual(raised.exception.code, "invalid-usage-normalizer-attestation")

    def test_descriptor_profile_distinguishes_fixture_and_qualified_status(self) -> None:
        fixture = {
            "contract": "adapter-local-usage-normalizer.v1",
            "status": "FIXTURE_ONLY",
            "acceptedForS1S2": False,
            "path": "adapters/qwen-code/usage_normalizer.py",
            "artifactFormat": "stream-jsonl",
            "maxArtifactBytes": 1024,
        }
        self.assertEqual(
            validate_usage_normalization_profile(fixture, adapter_id="qwen-code", host="qwen-code")["status"],
            "PASS",
        )

        falsely_qualified = {**fixture, "status": "QUALIFIED", "acceptedForS1S2": True}
        validation = validate_usage_normalization_profile(falsely_qualified, adapter_id="qwen-code", host="qwen-code")
        self.assertEqual(validation["status"], "FAIL")
        self.assertEqual(
            {item["code"] for item in validation["blockers"]},
            {"adapter-usage-normalization-host-range", "adapter-usage-normalization-evidence"},
        )


if __name__ == "__main__":
    unittest.main()
