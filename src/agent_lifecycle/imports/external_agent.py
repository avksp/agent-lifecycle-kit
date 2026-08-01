"""Generic agent-family external dialect import."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.imports.dialect_profiles import DEFAULT_PROFILE_ID
from agent_lifecycle.imports.external_dialects import import_external_dialect
from agent_lifecycle.imports.planning import DEFAULT_MAX_INPUT_BYTES, DEFAULT_TARGET_TOKENS


def import_external_agent(
    source_path: Path,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    package_id: str = "external-agent-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    return import_external_dialect(
        source_path,
        family="agent",
        profile_id=profile_id,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )
