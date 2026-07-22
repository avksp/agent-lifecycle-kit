from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ADAPTER_ROOT = ROOT / "adapters" / "claude"



def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


class ClaudeAdapterTests(unittest.TestCase):
    def test_claude_plugin_manifest_is_installable_projection(self) -> None:
        manifest = load_json(ADAPTER_ROOT / ".claude-plugin" / "plugin.json")
        self.assertEqual(manifest["name"], "agent-lifecycle-kit")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["skills"], "./skills")
        self.assertEqual(manifest["interface"]["displayName"], "Agent Lifecycle Kit")

    def test_descriptor_satisfies_shared_offline_baseline(self) -> None:
        descriptor = load_json(ADAPTER_ROOT / "adapter.descriptor.json")
        baseline = load_json(ROOT / "conformance" / "core" / "adapter-baseline.v1.json")
        required_operations = set(baseline["requiredOperations"])
        provided_operations = {item["name"] for item in descriptor["operations"]}

        self.assertEqual(descriptor["host"], "claude-code")
        self.assertEqual(descriptor["maturity"], "EXPERIMENTAL")
        self.assertIsNone(descriptor["liveTestedHostRange"])
        self.assertEqual(descriptor["unsupportedOperationPolicy"], "fail-closed")
        self.assertEqual(descriptor["contractCompatibility"], baseline["contractCompatibility"])
        self.assertTrue(required_operations.issubset(provided_operations))

    def test_offline_conformance_descriptor_passes_without_live_runtime(self) -> None:
        conformance = load_json(ROOT / "conformance" / "adapters" / "claude" / "offline-baseline.json")
        self.assertEqual(conformance["adapterId"], "claude")
        self.assertFalse(conformance["liveRuntimeRequired"])
        self.assertEqual(conformance["expectedResult"], "PASS")


if __name__ == "__main__":
    unittest.main()
