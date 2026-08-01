from __future__ import annotations

import json
from pathlib import Path

from agent_lifecycle.host_protocol import build_capability_manifest, validate_adapter_descriptor, validate_capability_manifest


ROOT = Path(__file__).resolve().parents[3]


def test_descriptor_and_capability_manifest_pass_offline_contracts() -> None:
    descriptor = _load_json(ROOT / "adapters/openinterpreter/adapter.descriptor.json")
    baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
    manifest = _load_json(ROOT / "adapters/openinterpreter/capabilities.manifest.json")

    assert validate_adapter_descriptor(descriptor, baseline=baseline)["status"] == "PASS"
    assert validate_capability_manifest(manifest, descriptor=descriptor)["status"] == "PASS"
    assert manifest == build_capability_manifest(descriptor)
    assert descriptor["nativeProjection"] == "host-local-compatible-cli"
    assert descriptor["hostCapabilities"] == []
    assert descriptor["maturity"] == "VERIFIED"
    assert descriptor["liveTestedHostRange"]["host"] == "openinterpreter"
    assert "docs/adapters/evidence/openinterpreter-live-verified.md" in descriptor["liveTestedHostRange"]["evidence"]


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value
