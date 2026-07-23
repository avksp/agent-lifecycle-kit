from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ADAPTER_ROOT = ROOT / "adapters" / "codex"

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


class CodexAdapterTests(unittest.TestCase):
    def test_codex_plugin_manifest_is_installable_projection(self) -> None:
        manifest = load_json(ADAPTER_ROOT / ".codex-plugin" / "plugin.json")
        self.assertEqual(manifest["name"], "agent-lifecycle-kit")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["skills"], "./skills")
        self.assertEqual(manifest["interface"]["displayName"], "Agent Lifecycle Kit")
        self.assertLessEqual(len(manifest["interface"]["defaultPrompt"]), 3)

    def test_descriptor_satisfies_shared_offline_baseline(self) -> None:
        descriptor = load_json(ADAPTER_ROOT / "adapter.descriptor.json")
        baseline = load_json(ROOT / "conformance" / "core" / "adapter-baseline.v1.json")
        required_operations = set(baseline["requiredOperations"])
        provided_operations = {item["name"] for item in descriptor["operations"]}

        self.assertEqual(descriptor["host"], "codex")
        self.assertEqual(descriptor["maturity"], "EXPERIMENTAL")
        self.assertIsNone(descriptor["liveTestedHostRange"])
        self.assertEqual(descriptor["unsupportedOperationPolicy"], "fail-closed")
        self.assertEqual(descriptor["contractCompatibility"], baseline["contractCompatibility"])
        self.assertEqual(descriptor["modelRouting"]["status"], "advisory")
        self.assertFalse(descriptor["modelRouting"]["providerModelNamesInCore"])
        self.assertTrue(required_operations.issubset(provided_operations))

    def test_offline_conformance_descriptor_passes_without_live_runtime(self) -> None:
        conformance = load_json(ROOT / "conformance" / "adapters" / "codex" / "offline-baseline.json")
        self.assertEqual(conformance["adapterId"], "codex")
        self.assertFalse(conformance["liveRuntimeRequired"])
        self.assertEqual(conformance["expectedResult"], "PASS")

    def test_codex_adapter_files_are_project_neutral(self) -> None:
        roots = [ADAPTER_ROOT, ROOT / "conformance" / "adapters" / "codex"]
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
