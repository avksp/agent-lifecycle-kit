from __future__ import annotations

import json
from pathlib import Path

from agent_lifecycle.host_protocol import (
    build_capability_manifest,
    validate_adapter_descriptor,
    validate_capability_manifest,
    validate_host_capabilities,
)


ROOT = Path(__file__).resolve().parents[3]


def test_descriptor_and_capability_manifest_pass_offline_contracts() -> None:
    descriptor = _load_json(ROOT / "adapters/pi/adapter.descriptor.json")
    baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
    manifest = _load_json(ROOT / "adapters/pi/capabilities.manifest.json")

    assert validate_adapter_descriptor(descriptor, baseline=baseline)["status"] == "PASS"
    assert validate_capability_manifest(manifest, descriptor=descriptor)["status"] == "PASS"
    assert manifest == build_capability_manifest(descriptor)
    assert descriptor["nativeProjection"] == "rpc-json-skills"
    assert descriptor["maturity"] == "VERIFIED"


def test_transport_capability_is_not_claimed_for_alternate_protocol() -> None:
    descriptor = _load_json(ROOT / "adapters/pi/adapter.descriptor.json")
    capability = descriptor["hostCapabilities"][0]

    assert validate_host_capabilities([capability], adapter_id="pi", host="pi")["status"] == "PASS"
    assert capability["capabilityId"] == "acp"
    assert capability["support"] == "unsupported"
    assert capability["evidencePolicy"] == "not-claimed"
    assert capability["probe"] is None
    assert capability["invocationContract"] is None


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value
