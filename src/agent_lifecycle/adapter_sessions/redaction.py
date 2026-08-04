"""Redaction helpers for adapter session receipts."""

from __future__ import annotations

SENSITIVE_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def redact_env_names(names: list[str]) -> dict[str, object]:
    return {
        "includedNames": sorted(set(names)),
        "valuesRedacted": True,
        "secretValuesStored": False,
    }


def redact_text(value: str) -> str:
    text = value
    for marker in SENSITIVE_MARKERS:
        text = _redact_marker(text, marker)
    return text


def _redact_marker(text: str, marker: str) -> str:
    words = []
    for word in text.split():
        if marker in word.upper() and "=" in word:
            words.append(word.split("=", 1)[0] + "=<redacted>")
        else:
            words.append(word)
    return " ".join(words)
