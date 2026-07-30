"""Receipt normalizer for the adapter projection."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.host_protocol import normalize_host_operation_receipt


def normalize_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Qwen Code host receipt into the portable contract."""
    return normalize_host_operation_receipt(payload)
