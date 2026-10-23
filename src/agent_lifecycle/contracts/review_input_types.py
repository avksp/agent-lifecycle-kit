"""Neutral typed inputs for review preparation; no IO or lifecycle authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


@dataclass(frozen=True)
class ReviewPacketRequest:
    """Inputs accepted by the review-packet application service."""

    manifest: str
    baseline: str | None = None
    max_bytes: int = 98304
    out: str | None = None
    subject_out: str | None = None


class ReviewSubject(TypedDict):
    """Validated physical inputs with unchanged JSON field names."""

    manifest: dict[str, Any]
    fileDigests: dict[str, str]
    runtimeInputs: dict[str, str]
