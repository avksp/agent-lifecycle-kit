from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.lifecycle_control_definitions import (  # noqa: E402
    CONTROL_LEVELS,
    QUALIFICATION_STATUSES,
)
from agent_lifecycle.host_protocol import (  # noqa: E402
    validate_adapter_descriptor,
    validate_capability_manifest,
    validate_event_capture_conformance,
)

ADAPTER_IDS = (
    "claude",
    "codex",
    "cursor",
    "gemini-cli",
    "goose",
    "grok-build",
    "hermes",
    "kimi-code",
    "opencode",
    "openinterpreter",
    "pi",
    "qwen-code",
)


class LifecycleControlCapabilityTests(unittest.TestCase):
    def test_all_adapters_publish_honest_operation_levels_and_valid_manifests(self) -> None:
        adapter_dirs = sorted(path.parent.name for path in (ROOT / "adapters").glob("*/adapter.descriptor.json"))
        self.assertEqual(tuple(adapter_dirs), ADAPTER_IDS)
        ranks = {level: index for index, level in enumerate(CONTROL_LEVELS)}

        for adapter_id in ADAPTER_IDS:
            with self.subTest(adapter=adapter_id):
                descriptor = _load_json(ROOT / "adapters" / adapter_id / "adapter.descriptor.json")
                manifest = _load_json(ROOT / "adapters" / adapter_id / "capabilities.manifest.json")

                descriptor_validation = validate_adapter_descriptor(descriptor)
                self.assertEqual(descriptor_validation["status"], "PASS")
                manifest_validation = validate_capability_manifest(manifest, descriptor=descriptor)
                self.assertEqual(manifest_validation["status"], "PASS")

                descriptor_operations = _by_name(descriptor["operations"])
                manifest_capabilities = _by_name(manifest["capabilities"])
                self.assertEqual(set(descriptor_operations), set(manifest_capabilities))

                for operation_name, operation in descriptor_operations.items():
                    capability = manifest_capabilities[operation_name]
                    for entry in (operation, capability):
                        self.assertIn(entry["declaredLevel"], CONTROL_LEVELS)
                        self.assertIn(entry["supportedLevel"], CONTROL_LEVELS)
                        self.assertIn(entry["qualifiedLevel"], CONTROL_LEVELS)
                        self.assertIn(entry["qualificationStatus"], QUALIFICATION_STATUSES)
                        self.assertGreaterEqual(ranks[entry["declaredLevel"]], ranks[entry["supportedLevel"]])
                        self.assertGreaterEqual(ranks[entry["supportedLevel"]], ranks[entry["qualifiedLevel"]])
                    self.assertEqual(operation["declaredLevel"], "GUIDANCE_ONLY")
                    self.assertEqual(operation["supportedLevel"], "GUIDANCE_ONLY")
                    self.assertEqual(operation["qualifiedLevel"], "GUIDANCE_ONLY")
                    self.assertEqual(operation["qualificationStatus"], "NO_RECOMMENDATION")
                    self.assertEqual(operation["qualifiedLevel"], capability["qualifiedLevel"])

                self.assertEqual(descriptor["eventCapture"]["status"], "DECLARED")
                self.assertEqual(descriptor["managedLaunch"]["status"], "WRAPPER_ONLY")
                events = _load_json(ROOT / "conformance" / "adapters" / adapter_id / "event-stream.json")
                receipt = _load_json(ROOT / "conformance" / "adapters" / adapter_id / "event-stream-receipt.json")
                conformance = validate_event_capture_conformance(
                    descriptor=descriptor,
                    capability_manifest=manifest,
                    events=events,
                    receipt=receipt,
                )
                self.assertEqual(conformance["status"], "PASS")

    def test_receipt_cannot_survive_descriptor_drift(self) -> None:
        adapter_id = "claude"
        descriptor = _load_json(ROOT / "adapters" / adapter_id / "adapter.descriptor.json")
        manifest = _load_json(ROOT / "adapters" / adapter_id / "capabilities.manifest.json")
        events = _load_json(ROOT / "conformance" / "adapters" / adapter_id / "event-stream.json")
        receipt = _load_json(ROOT / "conformance" / "adapters" / adapter_id / "event-stream-receipt.json")
        changed = copy.deepcopy(descriptor)
        changed["operations"][0]["qualifiedLevel"] = "OBSERVED"

        result = validate_event_capture_conformance(
            descriptor=changed,
            capability_manifest=manifest,
            events=events,
            receipt=receipt,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "adapter-event-descriptor-stale",
            {item["code"] for item in result["blockers"]},
        )


def _by_name(items: list[dict]) -> dict[str, dict]:
    return {item["name"]: item for item in items}


def _load_json(path: Path) -> Any:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value


if __name__ == "__main__":
    unittest.main()
