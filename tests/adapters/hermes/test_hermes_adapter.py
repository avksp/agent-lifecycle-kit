from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ADAPTER_ROOT = ROOT / "adapters" / "hermes"

PROJECT_MARKERS = (
    "board" + "-app",
    "board" + "2.0",
    "Dot" + "Space",
    "/Vol" + "umes/",
    "/Us" + "ers/",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


class HermesAdapterTests(unittest.TestCase):
    def test_hermes_registry_declares_skill_directory_and_commands(self) -> None:
        registry = load_json(ADAPTER_ROOT / "hermes.registry.json")
        commands = load_json(ADAPTER_ROOT / "slash-commands.json")
        self.assertEqual(registry["package"], "agent-lifecycle-kit")
        self.assertEqual(registry["skillsDirectory"], "./skills")
        self.assertEqual(registry["commands"], "./slash-commands.json")
        self.assertEqual(commands["slashCommandSupport"], "optional-host-capability")
        self.assertTrue(any(item["skill"] == "agent-workflow-orchestrator" for item in commands["commands"]))

    def test_descriptor_satisfies_shared_offline_baseline(self) -> None:
        descriptor = load_json(ADAPTER_ROOT / "adapter.descriptor.json")
        baseline = load_json(ROOT / "conformance" / "core" / "adapter-baseline.v1.json")
        required_operations = set(baseline["requiredOperations"])
        provided_operations = {item["name"] for item in descriptor["operations"]}

        self.assertEqual(descriptor["host"], "hermes")
        self.assertEqual(descriptor["maturity"], "EXPERIMENTAL")
        self.assertIsNone(descriptor["liveTestedHostRange"])
        self.assertEqual(descriptor["skillDiscovery"], "skill-directory")
        self.assertEqual(descriptor["slashCommandInvocation"], "optional-host-capability")
        self.assertEqual(descriptor["unsupportedOperationPolicy"], "fail-closed")
        self.assertEqual(descriptor["contractCompatibility"], baseline["contractCompatibility"])
        self.assertTrue(required_operations.issubset(provided_operations))

    def test_offline_conformance_descriptor_passes_without_live_runtime(self) -> None:
        conformance = load_json(ROOT / "conformance" / "adapters" / "hermes" / "offline-baseline.json")
        self.assertEqual(conformance["adapterId"], "hermes")
        self.assertFalse(conformance["liveRuntimeRequired"])
        self.assertEqual(conformance["expectedResult"], "PASS")

    def test_hermes_adapter_files_are_project_neutral(self) -> None:
        roots = [ADAPTER_ROOT, ROOT / "conformance" / "adapters" / "hermes"]
        for root in roots:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8")
                with self.subTest(path=path.relative_to(ROOT).as_posix()):
                    for marker in PROJECT_MARKERS:
                        self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
