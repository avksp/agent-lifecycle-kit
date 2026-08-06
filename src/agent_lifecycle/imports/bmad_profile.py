"""BMAD planning and story import profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    import_planning_input,
    planning_dialect_profile,
)


def bmad_profile(
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    return planning_dialect_profile(
        dialect_id="bmad-method-planning",
        dialect_kind="bmad",
        markers=["bmad", "prd", "architecture", "story", "dev agent record"],
        mapping={
            "title": ["h1", "story title", "epic", "prd"],
            "requirements": ["acceptance criteria", "tasks", "story", "requirements"],
            "reviewHints": ["architecture notes", "testing", "definition of done"],
        },
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )


def import_bmad_planning(
    source_path: Path,
    *,
    package_id: str = "bmad-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    profile = bmad_profile(max_input_bytes=max_input_bytes, target_tokens=target_tokens)
    return import_planning_input(
        source_path,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=profile,
    )
