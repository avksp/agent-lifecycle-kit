from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

HOSTS = {
    "claude": {
        "descriptorHost": "claude-code",
        "nativeManifest": ".claude-plugin/plugin.json",
        "nativeChecks": {"name": "agent-lifecycle-kit", "skills": "./skills"},
        "maturity": "VERIFIED",
        "modelRouting": True,
    },
    "codex": {
        "descriptorHost": "codex",
        "nativeManifest": ".codex-plugin/plugin.json",
        "nativeChecks": {"name": "agent-lifecycle-kit", "skills": "./skills"},
        "maturity": "VERIFIED",
        "modelRouting": True,
    },
    "cursor": {
        "descriptorHost": "cursor",
        "nativeManifest": ".cursor-plugin/plugin.json",
        "nativeChecks": {"name": "agent-lifecycle-kit", "skills": "./skills"},
    },
    "hermes": {
        "descriptorHost": "hermes",
        "registry": "hermes.registry.json",
        "commands": "slash-commands.json",
        "skillDiscovery": "skill-directory",
        "slashCommandInvocation": "optional-host-capability",
    },
    "opencode": {
        "descriptorHost": "opencode",
        "nativeManifest": "opencode.json",
        "modelRouting": True,
    },
}



class HostAdapterTests(unittest.TestCase):
    def test_host_native_projection_metadata_is_installable(self) -> None:
        for host, config in HOSTS.items():
            with self.subTest(host=host):
                adapter_root = ROOT / "adapters" / host
                if host == "hermes":
                    registry = load_json(adapter_root / config["registry"])
                    commands = load_json(adapter_root / config["commands"])
                    self.assertEqual(registry["package"], "agent-lifecycle-kit")
                    self.assertEqual(registry["skillsDirectory"], "./skills")
                    self.assertEqual(registry["commands"], "./slash-commands.json")
                    self.assertEqual(commands["slashCommandSupport"], "optional-host-capability")
                    self.assertTrue(any(item["skill"] == "agent-workflow-orchestrator" for item in commands["commands"]))
                elif host == "opencode":
                    manifest = load_json(adapter_root / config["nativeManifest"])
                    self.assertEqual(manifest["plugin"], ["./plugins/agent-lifecycle-kit.js"])
                    launcher = (adapter_root / "plugins/agent-lifecycle-kit.js").read_text(encoding="utf-8")
                    self.assertIn("agent-lifecycle-kit", launcher)
                    self.assertIn("fail-closed", launcher)
                else:
                    manifest = load_json(adapter_root / config["nativeManifest"])
                    self.assertEqual(manifest["name"], config["nativeChecks"]["name"])
                    self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
                    self.assertEqual(manifest["skills"], config["nativeChecks"]["skills"])
                    self.assertEqual(manifest["interface"]["displayName"], "Agent Lifecycle Kit")
                    if host == "codex":
                        self.assertLessEqual(len(manifest["interface"]["defaultPrompt"]), 3)

    def test_descriptor_satisfies_shared_offline_baseline(self) -> None:
        baseline = load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        required_operations = set(baseline["requiredOperations"])
        for host, config in HOSTS.items():
            with self.subTest(host=host):
                descriptor = load_json(ROOT / "adapters" / host / "adapter.descriptor.json")
                provided_operations = {item["name"] for item in descriptor["operations"]}
                expected_maturity = config.get("maturity", "EXPERIMENTAL")
                self.assertEqual(descriptor["host"], config["descriptorHost"])
                self.assertEqual(descriptor["maturity"], expected_maturity)
                if expected_maturity == "VERIFIED":
                    self.assertIsInstance(descriptor["liveTestedHostRange"], dict)
                    self.assertTrue(descriptor["liveTestedHostRange"]["evidence"])
                else:
                    self.assertIsNone(descriptor["liveTestedHostRange"])
                self.assertEqual(descriptor["unsupportedOperationPolicy"], "fail-closed")
                self.assertEqual(descriptor["contractCompatibility"], baseline["contractCompatibility"])
                self.assertTrue(required_operations.issubset(provided_operations))
                if config.get("skillDiscovery"):
                    self.assertEqual(descriptor["skillDiscovery"], config["skillDiscovery"])
                if config.get("slashCommandInvocation"):
                    self.assertEqual(descriptor["slashCommandInvocation"], config["slashCommandInvocation"])
                if config.get("modelRouting"):
                    self.assertEqual(descriptor["modelRouting"]["status"], "workflow-enforced")
                    self.assertEqual(descriptor["modelRouting"]["attemptRoutePolicy"], "must-execute-or-fail-closed")
                    self.assertTrue(descriptor["modelRouting"]["usageReceiptRequired"])
                    self.assertEqual(descriptor["modelRouting"]["liveVerified"], expected_maturity == "VERIFIED")
                    if host == "codex":
                        self.assertFalse(descriptor["modelRouting"]["providerModelNamesInCore"])
                    if host == "opencode":
                        self.assertEqual(descriptor["modelRouting"]["profileSupport"], "host-local")
                        self.assertEqual(descriptor["modelRouting"]["unsupportedClassPolicy"], "fail-closed")

    def test_offline_conformance_descriptor_passes_without_live_runtime(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                conformance = load_json(ROOT / "conformance" / "adapters" / host / "offline-baseline.json")
                self.assertEqual(conformance["adapterId"], host)
                self.assertFalse(conformance["liveRuntimeRequired"])
                self.assertEqual(conformance["expectedResult"], "PASS")



def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    unittest.main()
