"""AGENTS.md and agentskills dialect import helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.imports.constitution_adr import DIALECT_PROFILE_SCHEMA, validate_dialect_profile
from agent_lifecycle.imports.planning import DEFAULT_MAX_INPUT_BYTES, DEFAULT_TARGET_TOKENS, import_planning_input


def agentskills_profile(
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    body = {
        "schemaVersion": DIALECT_PROFILE_SCHEMA,
        "dialectId": "agents-agentskills",
        "dialectKind": "agentskills",
        "sourceTrusted": False,
        "requiresReview": True,
        "freezeBlocked": True,
        "markers": ["AGENTS.md", "agentskills", "skill", "instruction", "agent"],
        "resourceCaps": {"maxInputBytes": max_input_bytes, "targetTokens": target_tokens},
        "mapping": {
            "title": ["h1", "name", "skill name"],
            "requirements": ["rules", "instructions", "capabilities", "do-not-do bullets"],
            "candidateStatus": "DRAFT",
        },
    }
    return {**body, "profileDigest": canonical_digest(body)}


def import_agentskills_dialect(
    source_path: Path,
    *,
    package_id: str = "agentskills-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    profile = agentskills_profile(max_input_bytes=max_input_bytes, target_tokens=target_tokens)
    return import_planning_input(
        source_path,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=profile,
    )


def validate_agentskills_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return validate_dialect_profile(profile)
