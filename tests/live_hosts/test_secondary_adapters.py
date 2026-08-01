from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTAL_SECONDARY = ("pi",)


def test_secondary_adapters_are_experimental_without_live_range() -> None:
    for adapter_id in EXPERIMENTAL_SECONDARY:
        descriptor = _load_json(ROOT / "adapters" / adapter_id / "adapter.descriptor.json")
        conformance = _load_json(ROOT / "conformance" / "adapters" / adapter_id / "offline-baseline.json")

        assert descriptor["maturity"] == "EXPERIMENTAL"
        assert descriptor["liveTestedHostRange"] is None
        assert conformance["liveRuntimeRequired"] is False
        assert conformance["requiredMaturity"] == "EXPERIMENTAL"


def test_openinterpreter_secondary_adapter_is_verified_with_live_range() -> None:
    descriptor = _load_json(ROOT / "adapters/openinterpreter/adapter.descriptor.json")
    conformance = _load_json(ROOT / "conformance/adapters/openinterpreter/offline-baseline.json")

    assert descriptor["maturity"] == "VERIFIED"
    assert descriptor["modelRouting"]["liveVerified"] is True
    assert descriptor["liveTestedHostRange"]["host"] == "openinterpreter"
    assert "docs/adapters/evidence/openinterpreter-live-verified.md" in descriptor["liveTestedHostRange"]["evidence"]
    assert conformance["liveRuntimeRequired"] is False
    assert conformance["requiredMaturity"] == "EXPERIMENTAL"


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value
