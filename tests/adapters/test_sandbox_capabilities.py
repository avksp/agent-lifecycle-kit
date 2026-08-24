from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from agent_lifecycle.host_protocol import validate_capability_manifest
from agent_lifecycle.workflow.sandbox_receipts import validate_sandbox_capability

ROOT = Path(__file__).resolve().parents[2]


class AdapterSandboxCapabilityTests(unittest.TestCase):
    def test_current_adapters_declare_unknown_sandbox_capabilities_without_overclaim(self) -> None:
        for descriptor_path in sorted((ROOT / "adapters").glob("*/adapter.descriptor.json")):
            host = descriptor_path.parent.name
            with self.subTest(host=host):
                descriptor = _load_json(descriptor_path)
                manifest = _load_json(descriptor_path.with_name("capabilities.manifest.json"))
                capability = descriptor["sandboxCapabilities"]
                validation = validate_sandbox_capability(capability)
                manifest_validation = validate_capability_manifest(manifest, descriptor=descriptor)

                self.assertEqual(capability["schemaVersion"], "agent-sandbox-capability.v1")
                self.assertEqual(capability["status"], "UNKNOWN")
                self.assertFalse(capability["verified"])
                self.assertFalse(capability["productionPromotionClaimed"])
                self.assertTrue(capability["writeScopeBoundary"]["gitWriteScopeGovernedSeparately"])
                self.assertEqual({name for name in capability["boundaries"]}, {"filesystem", "network", "process", "environment"})
                self.assertEqual(validation["status"], "PASS")
                self.assertEqual(validation["unknownBoundaryCount"], 4)
                self.assertEqual(manifest["sandboxCapabilities"], capability)
                self.assertEqual(manifest_validation["status"], "PASS")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    unittest.main()
