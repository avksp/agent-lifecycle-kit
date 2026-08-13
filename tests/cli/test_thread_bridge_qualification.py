from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.host_protocol import build_capability_manifest
from agent_lifecycle.host_protocol.capabilities import (
    capability_manifest_identity,
    build_thread_bridge_profile_from_descriptor,
)
from agent_lifecycle.contracts.thread_bridge_schemas import (
    build_thread_bridge_profile,
    build_thread_bridge_qualification_receipt,
)


ROOT = Path(__file__).resolve().parents[2]


class ThreadBridgeQualificationCliTests(unittest.TestCase):
    def test_qualification_command_validates_a_supplied_receipt(self) -> None:
        descriptor_path = ROOT / "adapters/opencode/adapter.descriptor.json"
        manifest_path = ROOT / "adapters/opencode/capabilities.manifest.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        profile = build_thread_bridge_profile_from_descriptor(
            descriptor,
            capability_manifest_digest=capability_manifest_identity(manifest),
        )
        receipt = build_thread_bridge_qualification_receipt(
            receipt_id="qualification-cli-1",
            adapter_id=profile["adapterId"],
            host=profile["host"],
            descriptor_digest=canonical_digest(descriptor),
            capability_manifest_digest=capability_manifest_identity(manifest),
            host_range=profile["hostRange"],
            operation_set=["read"],
            evidence_refs=["work/qualification.json"],
        )
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            output = Path(directory) / "result.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            code = main(
                [
                    "adapter",
                    "thread-qualify",
                    "--descriptor",
                    str(descriptor_path),
                    "--manifest",
                    str(manifest_path),
                    "--receipt",
                    str(receipt_path),
                    "--out",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "FAIL")

    def test_qualified_wrapper_profile_passes_without_host_launch(self) -> None:
        descriptor = json.loads((ROOT / "adapters/opencode/adapter.descriptor.json").read_text(encoding="utf-8"))
        operations = list(descriptor["threadBridge"]["operations"])
        operations[0] = {**operations[0], "declaredStatus": "WRAPPER_ONLY"}
        descriptor["threadBridge"] = build_thread_bridge_profile(
            adapter_id=descriptor["adapterId"],
            host=descriptor["host"],
            operations=operations,
            host_range=descriptor["liveTestedHostRange"],
        )
        manifest = build_capability_manifest(descriptor)
        profile = build_thread_bridge_profile_from_descriptor(
            descriptor,
            capability_manifest_digest=capability_manifest_identity(manifest),
        )
        receipt = build_thread_bridge_qualification_receipt(
            receipt_id="qualification-cli-2",
            adapter_id=profile["adapterId"],
            host=profile["host"],
            descriptor_digest=canonical_digest(descriptor),
            capability_manifest_digest=capability_manifest_identity(manifest),
            host_range=profile["hostRange"],
            operation_set=["read"],
            evidence_refs=["work/qualification.json"],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor_path = root / "adapter.descriptor.json"
            manifest_path = root / "capabilities.manifest.json"
            receipt_path = root / "receipt.json"
            output = root / "result.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            code = main(
                [
                    "adapter",
                    "thread-qualify",
                    "--descriptor",
                    str(descriptor_path),
                    "--manifest",
                    str(manifest_path),
                    "--receipt",
                    str(receipt_path),
                    "--out",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["operations"][0]["capabilitySupport"], "supported")


if __name__ == "__main__":
    unittest.main()
