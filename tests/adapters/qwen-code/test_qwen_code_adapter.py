from __future__ import annotations

import json
from pathlib import Path

from agent_lifecycle.host_protocol import build_capability_manifest, validate_adapter_descriptor, validate_capability_manifest


ROOT = Path(__file__).resolve().parents[3]


def test_descriptor_and_capability_manifest_pass_offline_contracts() -> None:
    descriptor_path = ROOT / "adapters/qwen-code/adapter.descriptor.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "conformance/core/adapter-baseline.v1.json").read_text(encoding="utf-8"))
    manifest = build_capability_manifest(descriptor)

    assert validate_adapter_descriptor(descriptor, baseline=baseline)["status"] == "PASS"
    assert validate_capability_manifest(manifest, descriptor=descriptor)["status"] == "PASS"
    assert manifest["adapterId"] == "qwen-code"
