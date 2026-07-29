from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.host_protocol import validate_capability_manifest  # noqa: E402

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
    "gemini-cli": {
        "descriptorHost": "gemini-cli",
        "capabilityOnly": True,
        "modelRouting": True,
        "runnerStatus": "bounded-live-runner",
        "eventBridgeDispatch": "gemini-stream-json-to-host-operation-receipt",
    },
    "hermes": {
        "descriptorHost": "hermes",
        "registry": "hermes.registry.json",
        "commands": "slash-commands.json",
        "skillDiscovery": "skill-directory",
        "slashCommandInvocation": "optional-host-capability",
        "maturity": "VERIFIED",
        "modelRouting": True,
    },
    "kimi-code": {
        "descriptorHost": "kimi-code",
        "capabilityOnly": True,
        "modelRouting": True,
        "runnerStatus": "bounded-live-runner",
        "eventBridgeDispatch": "kimi-stream-json-to-host-operation-receipt",
    },
    "opencode": {
        "descriptorHost": "opencode",
        "nativeManifest": "opencode.json",
        "modelRouting": True,
        "maturity": "VERIFIED",
    },
    "qwen-code": {
        "descriptorHost": "qwen-code",
        "capabilityOnly": True,
        "modelRouting": True,
        "maturity": "VERIFIED",
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
                elif config.get("capabilityOnly"):
                    expected_maturity = config.get("maturity", "EXPERIMENTAL")
                    expected_runner = config.get(
                        "runnerStatus",
                        "bounded-live-runner" if expected_maturity == "VERIFIED" else "fail-closed-skeleton",
                    )
                    expected_dispatch = config.get(
                        "eventBridgeDispatch",
                        "qwen-stream-json-to-host-operation-receipt" if expected_maturity == "VERIFIED" else "not-implemented-fail-closed",
                    )
                    projection = load_json(adapter_root / "projection.manifest.json")
                    self.assertEqual(projection["receiptNormalizer"]["portableReceiptSchema"], "agent-host-operation-receipt.v1")
                    self.assertEqual(projection["maturity"], expected_maturity)
                    if expected_runner == "bounded-live-runner":
                        self.assertEqual(projection["runner"]["status"], "bounded-live-runner")
                        self.assertEqual(projection["receiptNormalizer"]["status"], "contract-normalizer")
                        self.assertEqual(projection["eventBridge"]["runtimeDispatch"], expected_dispatch)
                    else:
                        self.assertEqual(projection["runner"]["status"], "fail-closed-skeleton")
                        self.assertEqual(projection["eventBridge"]["runtimeDispatch"], expected_dispatch)
                        self.assertIn("fail closed", (adapter_root / "event-bridge.md").read_text(encoding="utf-8"))
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
                capability_manifest = load_json(ROOT / "adapters" / host / "capabilities.manifest.json")
                provided_operations = {item["name"] for item in descriptor["operations"]}
                expected_maturity = config.get("maturity", "EXPERIMENTAL")
                self.assertEqual(descriptor["host"], config["descriptorHost"])
                self.assertEqual(descriptor["maturity"], expected_maturity)
                self.assertEqual(descriptor["capabilityManifest"], f"adapters/{host}/capabilities.manifest.json")
                self.assertEqual(capability_manifest["host"], config["descriptorHost"])
                self.assertEqual(capability_manifest["maturity"], expected_maturity)
                self.assertFalse(capability_manifest["promotion"]["productionPromotionClaimed"])
                self.assertEqual(validate_capability_manifest(capability_manifest, descriptor=descriptor)["status"], "PASS")
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
                self.assertEqual(conformance["capabilityManifest"], f"adapters/{host}/capabilities.manifest.json")
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
