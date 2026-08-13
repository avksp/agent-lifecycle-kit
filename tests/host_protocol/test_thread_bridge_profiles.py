from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.thread_bridge_schemas import validate_thread_capability
from agent_lifecycle.host_protocol import (
    validate_capability_manifest,
)
from agent_lifecycle.host_protocol.capabilities import (
    build_thread_bridge_capability_projection,
    build_thread_bridge_profile_from_descriptor,
    capability_manifest_identity,
)


ROOT = Path(__file__).resolve().parents[2]


class ThreadBridgeHostProtocolTests(unittest.TestCase):
    def test_all_bundled_manifests_have_conservative_thread_profiles(self) -> None:
        descriptors = sorted((ROOT / "adapters").glob("*/adapter.descriptor.json"))
        self.assertEqual(len(descriptors), 12)
        for descriptor_path in descriptors:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            manifest = json.loads((descriptor_path.parent / "capabilities.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(validate_capability_manifest(manifest, descriptor=descriptor)["status"], "PASS")
            profile = manifest["threadBridge"]
            self.assertEqual(profile["descriptorDigest"], canonical_digest(descriptor))
            self.assertEqual(profile["capabilityManifestDigest"], capability_manifest_identity(manifest))
            self.assertEqual({item["declaredStatus"] for item in profile["operations"]}, {"UNSUPPORTED"})

    def test_projection_keeps_declaration_separate_from_qualification(self) -> None:
        descriptor = json.loads((ROOT / "adapters/opencode/adapter.descriptor.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "adapters/opencode/capabilities.manifest.json").read_text(encoding="utf-8"))
        profile = build_thread_bridge_profile_from_descriptor(
            descriptor,
            capability_manifest_digest=capability_manifest_identity(manifest),
        )
        projection = build_thread_bridge_capability_projection(profile)

        self.assertEqual(validate_thread_capability(projection)["status"], "PASS")
        self.assertEqual(projection["support"], "unsupported")
        self.assertTrue(all(item["qualificationStatus"] == "UNQUALIFIED" for item in projection["operations"]))
        self.assertTrue(all(item["capabilitySupport"] == "unsupported" for item in projection["operations"]))


if __name__ == "__main__":
    unittest.main()
