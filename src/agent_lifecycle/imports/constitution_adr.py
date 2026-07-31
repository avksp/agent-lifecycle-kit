"""Constitution/ADR dialect import helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.imports.planning import DEFAULT_MAX_INPUT_BYTES, DEFAULT_TARGET_TOKENS, import_planning_input

DIALECT_PROFILE_SCHEMA = "agent-import-dialect-profile.v1"
DIALECT_PROFILE_VALIDATION_SCHEMA = "agent-import-dialect-profile-validation.v1"


def constitution_adr_profile(
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    body = {
        "schemaVersion": DIALECT_PROFILE_SCHEMA,
        "dialectId": "constitution-adr",
        "dialectKind": "constitution-adr",
        "sourceTrusted": False,
        "requiresReview": True,
        "freezeBlocked": True,
        "markers": ["constitution", "adr", "decision", "constraints", "principles"],
        "resourceCaps": {"maxInputBytes": max_input_bytes, "targetTokens": target_tokens},
        "mapping": {
            "title": ["h1", "title"],
            "requirements": ["principles", "constraints", "decision bullets", "numbered decisions"],
            "candidateStatus": "DRAFT",
        },
    }
    return {**body, "profileDigest": canonical_digest(body)}


def import_constitution_adr(
    source_path: Path,
    *,
    package_id: str = "constitution-adr-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    profile = constitution_adr_profile(max_input_bytes=max_input_bytes, target_tokens=target_tokens)
    return import_planning_input(
        source_path,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=profile,
    )


def validate_dialect_profile(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        raise LifecycleError("invalid-dialect-profile", "dialect profile must be an object")
    if profile.get("schemaVersion") != DIALECT_PROFILE_SCHEMA:
        blockers.append({"code": "dialect-profile-schema-invalid"})
    if not isinstance(profile.get("dialectId"), str) or not profile["dialectId"]:
        blockers.append({"code": "dialect-profile-id-missing"})
    if not isinstance(profile.get("dialectKind"), str) or not profile["dialectKind"]:
        blockers.append({"code": "dialect-profile-kind-missing"})
    if profile.get("sourceTrusted") is not False:
        blockers.append({"code": "dialect-profile-source-trusted"})
    if profile.get("requiresReview") is not True:
        blockers.append({"code": "dialect-profile-review-not-required"})
    if profile.get("freezeBlocked") is not True:
        blockers.append({"code": "dialect-profile-freeze-not-blocked"})
    markers = profile.get("markers")
    if markers is not None and (not isinstance(markers, list) or not all(isinstance(item, str) and item for item in markers)):
        blockers.append({"code": "dialect-profile-markers-invalid"})
    expected_digest = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
    if profile.get("profileDigest") != expected_digest:
        blockers.append({"code": "dialect-profile-digest-mismatch"})
    body = {
        "schemaVersion": DIALECT_PROFILE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "dialectId": profile.get("dialectId"),
        "dialectKind": profile.get("dialectKind"),
        "blockers": blockers,
        "profileDigest": profile.get("profileDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_dialect_profile_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("dialect-profile-validation-failed", "dialect profile validation failed", {"validation": validation})
    return validation
