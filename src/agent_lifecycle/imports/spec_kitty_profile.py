"""Spec Kitty planning import profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    import_planning_input,
    planning_dialect_profile,
)


def spec_kitty_profile(
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    return planning_dialect_profile(
        dialect_id="spec-kitty-planning",
        dialect_kind="spec-kitty",
        markers=["spec kitty", "requirements", "design", "tasks", "verification"],
        mapping={
            "title": ["h1", "feature", "spec"],
            "requirements": ["requirements", "design", "tasks", "verification"],
            "reviewHints": ["open questions", "risks", "checks"],
        },
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )


def import_spec_kitty_planning(
    source_path: Path,
    *,
    package_id: str = "spec-kitty-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    profile = spec_kitty_profile(max_input_bytes=max_input_bytes, target_tokens=target_tokens)
    return import_planning_input(
        source_path,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=profile,
    )
