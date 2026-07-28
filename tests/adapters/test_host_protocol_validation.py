from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.host_protocol import validate_adapter_descriptor  # noqa: E402


class HostProtocolAdapterValidationTests(unittest.TestCase):
    def test_current_adapter_descriptors_validate_through_shared_baseline(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        for descriptor_path in sorted((ROOT / "adapters").glob("*/adapter.descriptor.json")):
            with self.subTest(path=descriptor_path.relative_to(ROOT).as_posix()):
                result = validate_adapter_descriptor(_load_json(descriptor_path), baseline=baseline)
                self.assertEqual(result["status"], "PASS")
                self.assertIn("agent-host-operation-request.v1", result["hostProtocolContracts"])

    def test_host_operation_examples_validate_through_contract_path(self) -> None:
        descriptor = _load_json(ROOT / "adapters/codex/adapter.descriptor.json")
        examples = _load_json(ROOT / "conformance/adapters/host-operation-examples.v1.json")["examples"]
        requests = [item["request"] for item in examples]
        receipts = [item["receipt"] for item in examples]

        result = validate_adapter_descriptor(descriptor, requests=requests, receipts=receipts)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["requestCount"], 13)
        self.assertEqual(result["receiptCount"], 13)

    def test_verified_adapter_without_live_evidence_fails(self) -> None:
        # NEG-R03-07 Runtime Adapter Overclaim
        descriptor = _load_json(ROOT / "adapters/codex/adapter.descriptor.json")
        descriptor["maturity"] = "VERIFIED"
        descriptor["liveTestedHostRange"] = None

        result = validate_adapter_descriptor(descriptor)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("verified-adapter-without-live-evidence", {item["code"] for item in result["blockers"]})

    def test_host_protocol_bypass_shape_is_rejected_by_contracts(self) -> None:
        # NEG-R03-19 Host Protocol Contract Bypass
        descriptor = _load_json(ROOT / "adapters/codex/adapter.descriptor.json")
        request = _request()
        request["hostLocalField"] = "would be accepted by a loose parser"

        with self.assertRaises(LifecycleError) as raised:
            validate_adapter_descriptor(descriptor, requests=[request])

        self.assertEqual(raised.exception.code, "unknown-field")

    def test_host_receipt_capability_mismatch_fails_validation(self) -> None:
        descriptor = _load_json(ROOT / "adapters/codex/adapter.descriptor.json")
        receipt = _receipt()
        receipt["capability"] = "different-capability"

        result = validate_adapter_descriptor(descriptor, requests=[_request()], receipts=[receipt])

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("host-receipt-capability-mismatch", {item["code"] for item in result["blockers"]})


def _request() -> dict:
    return {
        "schemaVersion": "agent-host-operation-request.v1",
        "operationId": "adapter-op-1",
        "capability": "install",
        "inputs": {},
        "outputs": [{"role": "receipt", "path": "out/receipt.json"}],
        "constraints": {"network": "denied"},
    }


def _receipt() -> dict:
    return {
        "schemaVersion": "agent-host-operation-receipt.v1",
        "operationId": "adapter-op-1",
        "capability": "install",
        "status": "PASS",
        "outputs": [],
        "usage": {},
    }


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


if __name__ == "__main__":
    unittest.main()
