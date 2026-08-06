"""OpenSpec planning import profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    import_planning_input,
    planning_dialect_profile,
)


def openspec_profile(
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    return planning_dialect_profile(
        dialect_id="openspec-planning",
        dialect_kind="openspec",
        markers=["openspec", "spec", "proposal", "capability", "change"],
        mapping={
            "title": ["h1", "title", "spec name", "proposal"],
            "requirements": ["requirements", "acceptance", "capabilities", "changes"],
            "reviewHints": ["risks", "validation", "migration"],
        },
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )


def import_openspec_planning(
    source_path: Path,
    *,
    package_id: str = "openspec-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    profile = openspec_profile(max_input_bytes=max_input_bytes, target_tokens=target_tokens)
    return import_planning_input(
        source_path,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=profile,
    )
