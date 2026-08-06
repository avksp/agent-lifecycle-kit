"""GitHub Spec Kit planning import profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    import_planning_input,
    planning_dialect_profile,
)


def spec_kit_profile(
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    return planning_dialect_profile(
        dialect_id="github-spec-kit-planning",
        dialect_kind="spec-kit",
        markers=["spec-kit", "specification", "plan", "tasks", "acceptance"],
        mapping={
            "title": ["h1", "feature", "specification"],
            "requirements": ["user stories", "functional requirements", "acceptance criteria", "tasks"],
            "reviewHints": ["edge cases", "constraints", "test plan"],
        },
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )


def import_spec_kit_planning(
    source_path: Path,
    *,
    package_id: str = "spec-kit-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    profile = spec_kit_profile(max_input_bytes=max_input_bytes, target_tokens=target_tokens)
    return import_planning_input(
        source_path,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=profile,
    )
