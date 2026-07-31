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
    descriptor_path = ROOT / "adapters/goose/adapter.descriptor.json"
    descriptor = _load_json(descriptor_path)
    baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
    manifest = _load_json(ROOT / "adapters/goose/capabilities.manifest.json")

    assert validate_adapter_descriptor(descriptor, baseline=baseline)["status"] == "PASS"
    assert validate_capability_manifest(manifest, descriptor=descriptor)["status"] == "PASS"
    assert manifest == build_capability_manifest(descriptor)
    assert manifest["adapterId"] == "goose"
    assert manifest["hostCapabilities"][0]["capabilityId"] == "acp"


def test_descriptor_rejects_invalid_acp_capability_claim() -> None:
    descriptor = _load_json(ROOT / "adapters/goose/adapter.descriptor.json")
    descriptor["hostCapabilities"][0]["providerIdentityUsed"] = True

    result = validate_adapter_descriptor(descriptor)

    assert result["status"] == "FAIL"
    nested_codes = {
        blocker["code"]
        for item in result["blockers"]
        if item["code"] == "adapter-host-capability-invalid"
        for blocker in item["blockers"]
    }
    assert "host-capability-provider-identity" in nested_codes


def test_goose_acp_host_capability_is_probe_required() -> None:
    descriptor = _load_json(ROOT / "adapters/goose/adapter.descriptor.json")
    capability = descriptor["hostCapabilities"][0]

    validation = validate_host_capabilities([capability], adapter_id="goose", host="goose")

    assert validation["status"] == "PASS"
    assert capability["support"] == "supported"
    assert capability["evidencePolicy"] == "probe-required"
    assert capability["probe"]["liveCallsStarted"] is False


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value
