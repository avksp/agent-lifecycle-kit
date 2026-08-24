"""Shared redaction for bounded process receipts."""

from __future__ import annotations

import re

from agent_lifecycle.contracts.public_locators import normalize_public_locator
from agent_lifecycle.contracts.redaction import redact_text as _redact_text

_POSIX_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9_.:/-])/(?!/)[^\s\"'<>]+")
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:\\[^\s\"'<>]+")


def redact_env_names(names: list[str]) -> dict[str, object]:
    return {
        "includedNames": sorted(set(names)),
        "valuesRedacted": True,
        "secretValuesStored": False,
    }


def redact_text(value: str) -> str:
    return _redact_text(value)[0]


def redact_process_text(value: str) -> tuple[str, bool]:
    """Redact secrets and arbitrary absolute paths from host process output."""

    redacted, changed = _redact_text(value)
    redacted = _WINDOWS_ABSOLUTE_PATH.sub("<redacted>", redacted)
    redacted = _POSIX_ABSOLUTE_PATH.sub("<redacted>", redacted)
    return redacted, changed or redacted != value


__all__ = ["normalize_public_locator", "redact_env_names", "redact_process_text", "redact_text"]
