from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.host_protocol import (
    build_capability_manifest,
    normalize_host_operation_receipt,
    validate_capability_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


class AdapterCapabilityManifestTests(unittest.TestCase):
    def test_manifest_is_derived_from_descriptor_without_promotion_claims(self) -> None:
        descriptor = _load_json(ROOT / "adapters/opencode/adapter.descriptor.json")

        manifest = build_capability_manifest(descriptor)
        validation = validate_capability_manifest(manifest, descriptor=descriptor)

        self.assertEqual(manifest["schemaVersion"], "agent-adapter-capability-manifest.v1")
        self.assertEqual(manifest["adapterId"], "opencode")
        self.assertEqual(manifest["host"], "opencode")
        self.assertEqual(manifest["maturity"], "VERIFIED")
        self.assertFalse(manifest["promotion"]["productionPromotionClaimed"])
        self.assertEqual(manifest["runtimeBoundary"]["lifecycleSemantics"], "delegated-to-agent-lifecycle-core")
        self.assertFalse(manifest["runtimeBoundary"]["providerModelNamesInCore"])
        self.assertEqual(len(manifest["capabilities"]), len(descriptor["operations"]))
        self.assertIn("adapter-event-stream", {item["name"] for item in manifest["capabilities"]})
        self.assertEqual(validation["status"], "PASS")

    def test_manifest_validation_fails_on_descriptor_drift(self) -> None:
        descriptor = _load_json(ROOT / "adapters/opencode/adapter.descriptor.json")
        manifest = build_capability_manifest(descriptor)
        manifest["capabilities"] = manifest["capabilities"][:-1]

        validation = validate_capability_manifest(manifest, descriptor=descriptor)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("capability-required-operation-missing", codes)
        self.assertIn("capability-manifest-operation-drift", codes)

    def test_receipt_normalizer_redacts_sensitive_nested_values(self) -> None:
        payload = {
            "schemaVersion": "agent-host-operation-receipt.v1",
            "operationId": "op-1",
            "capability": "launch",
            "status": "PASS",
            "outputs": [{"path": "tasks/out.json", "apiKey": "secret-value"}],
            "usage": {"inputTokens": 10, "provider": {"session-token": "abc"}},
        }

        normalized = normalize_host_operation_receipt(payload)

        self.assertEqual(normalized["outputs"][0]["apiKey"], "<redacted>")
        self.assertEqual(normalized["usage"]["provider"]["session-token"], "<redacted>")
        self.assertEqual(normalized["usage"]["inputTokens"], 10)


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


if __name__ == "__main__":
    unittest.main()
