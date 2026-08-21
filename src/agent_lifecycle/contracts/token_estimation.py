"""Deterministic token-size estimates shared by bounded envelopes."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_bytes


def estimate_tokens(value: Any) -> int:
    """Estimate UTF-8 JSON tokens without importing a context domain package."""

    return max(1, (len(canonical_bytes(value)) + 3) // 4)


__all__ = ["estimate_tokens"]
