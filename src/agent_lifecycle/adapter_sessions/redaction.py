"""Adapter-session compatibility helpers for shared receipt redaction."""

from __future__ import annotations

from agent_lifecycle.contracts.redaction import redact_text as _redact_text


def redact_env_names(names: list[str]) -> dict[str, object]:
    return {
        "includedNames": sorted(set(names)),
        "valuesRedacted": True,
        "secretValuesStored": False,
    }


def redact_text(value: str) -> str:
    """Return the shared redacted text for legacy adapter-session callers."""

    return _redact_text(value)[0]
