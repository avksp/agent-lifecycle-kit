from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ADAPTER_ROOT = ROOT / "adapters" / "opencode"



def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


class OpenCodeAdapterTests(unittest.TestCase):
    def test_opencode_manifest_points_to_launcher(self) -> None:
        manifest = load_json(ADAPTER_ROOT / "opencode.json")
        self.assertEqual(manifest["plugin"], ["./plugins/agent-lifecycle-kit.js"])
        launcher = (ADAPTER_ROOT / "plugins" / "agent-lifecycle-kit.js").read_text(encoding="utf-8")
        self.assertIn("agent-lifecycle-kit", launcher)
        self.assertIn("fail-closed", launcher)

    def test_descriptor_satisfies_shared_offline_baseline(self) -> None:
        descriptor = load_json(ADAPTER_ROOT / "adapter.descriptor.json")
        baseline = load_json(ROOT / "conformance" / "core" / "adapter-baseline.v1.json")
        required_operations = set(baseline["requiredOperations"])
        provided_operations = {item["name"] for item in descriptor["operations"]}

        self.assertEqual(descriptor["host"], "opencode")
        self.assertEqual(descriptor["maturity"], "EXPERIMENTAL")
        self.assertIsNone(descriptor["liveTestedHostRange"])
        self.assertEqual(descriptor["unsupportedOperationPolicy"], "fail-closed")
        self.assertEqual(descriptor["contractCompatibility"], baseline["contractCompatibility"])
        self.assertEqual(descriptor["modelRouting"]["profileSupport"], "host-local")
        self.assertEqual(descriptor["modelRouting"]["unsupportedClassPolicy"], "fail-closed")
        self.assertTrue(required_operations.issubset(provided_operations))

    def test_offline_conformance_descriptor_passes_without_live_runtime(self) -> None:
        conformance = load_json(ROOT / "conformance" / "adapters" / "opencode" / "offline-baseline.json")
        self.assertEqual(conformance["adapterId"], "opencode")
        self.assertFalse(conformance["liveRuntimeRequired"])
        self.assertEqual(conformance["expectedResult"], "PASS")


if __name__ == "__main__":
    unittest.main()
