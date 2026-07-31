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
    descriptor = _load_json(ROOT / "adapters/grok-build/adapter.descriptor.json")
    baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
    manifest = _load_json(ROOT / "adapters/grok-build/capabilities.manifest.json")

    assert validate_adapter_descriptor(descriptor, baseline=baseline)["status"] == "PASS"
    assert validate_capability_manifest(manifest, descriptor=descriptor)["status"] == "PASS"
    assert manifest == build_capability_manifest(descriptor)
    assert descriptor["maturity"] == "VERIFIED"
    assert descriptor["liveTestedHostRange"]["minimumVersion"] == "0.2.117"
    assert descriptor["modelRouting"]["liveVerified"] is True


def test_acp_capability_is_probe_gated_with_positive_and_negative_receipts() -> None:
    descriptor = _load_json(ROOT / "adapters/grok-build/adapter.descriptor.json")
    capability = descriptor["hostCapabilities"][0]
    probe = _load_json(ROOT / "conformance/adapters/grok-build/grok-acp-probe-negative-fixture.json")
    positive_probe = _load_json(ROOT / "conformance/adapters/grok-build/grok-acp-probe-positive-fixture.json")

    assert validate_host_capabilities([capability], adapter_id="grok-build", host="grok-build")["status"] == "PASS"
    assert capability["support"] == "supported"
    assert capability["evidencePolicy"] == "probe-required"
    assert capability["probe"]["command"] == ["grok", "agent", "--help"]
    assert capability["probe"]["liveCallsStarted"] is False
    assert probe["status"] == "FAIL"
    assert {item["code"] for item in probe["blockers"]} == {"acp-executable-missing", "acp-probe-failed"}
    assert probe["liveCallsStarted"] is False
    assert positive_probe["status"] == "PASS"
    assert positive_probe["blockers"] == []
    assert positive_probe["liveCallsStarted"] is False


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value
