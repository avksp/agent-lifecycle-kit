from __future__ import annotations

import json
from pathlib import Path

from agent_lifecycle.host_protocol import build_acp_probe_receipt


ROOT = Path(__file__).resolve().parents[2]


def test_goose_probe_receipt_passes_without_live_model_call_when_probe_is_valid() -> None:
    descriptor = _load_json(ROOT / "adapters/goose/adapter.descriptor.json")
    receipt = build_acp_probe_receipt(
        descriptor["hostCapabilities"][0],
        executable_found=True,
        probe_passed=True,
        invocation_contract_valid=True,
    )

    assert receipt["schemaVersion"] == "agent-acp-probe-receipt.v1"
    assert receipt["status"] == "PASS"
    assert receipt["host"] == "goose"
    assert receipt["liveCallsStarted"] is False


def test_goose_probe_receipt_fails_closed_on_missing_executable() -> None:
    descriptor = _load_json(ROOT / "adapters/goose/adapter.descriptor.json")
    receipt = build_acp_probe_receipt(
        descriptor["hostCapabilities"][0],
        executable_found=False,
        probe_passed=True,
        invocation_contract_valid=True,
    )

    assert receipt["status"] == "FAIL"
    assert "acp-executable-missing" in {item["code"] for item in receipt["blockers"]}


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value
