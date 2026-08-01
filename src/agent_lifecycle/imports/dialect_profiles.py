"""Generic external dialect profile registry."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.imports.constitution_adr import DIALECT_PROFILE_SCHEMA, validate_dialect_profile
from agent_lifecycle.imports.planning import DEFAULT_MAX_INPUT_BYTES, DEFAULT_TARGET_TOKENS

EXTERNAL_DIALECT_REGISTRY_SCHEMA = "agent-external-dialect-profile-registry.v1"
EXTERNAL_DIALECT_FAMILIES = ("workflow", "agent")
DEFAULT_PROFILE_ID = "generic"

_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def external_dialect_profile(
    family: str,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    """Build a provider-neutral import profile for a generic external family."""

    _validate_family(family)
    _validate_profile_id(profile_id)
    body = {
        "schemaVersion": DIALECT_PROFILE_SCHEMA,
        "dialectId": f"external-{family}-{profile_id}",
        "dialectKind": f"external-{family}",
        "family": family,
        "profileId": profile_id,
        "sourceTrusted": False,
        "requiresReview": True,
        "freezeBlocked": True,
        "markers": _markers_for_family(family),
        "resourceCaps": {"maxInputBytes": max_input_bytes, "targetTokens": target_tokens},
        "mapping": _mapping_for_family(family),
    }
    return {**body, "profileDigest": canonical_digest(body)}


def external_dialect_registry() -> dict[str, Any]:
    profiles = [
        {
            "family": family,
            "profileId": DEFAULT_PROFILE_ID,
            "dialectId": f"external-{family}-{DEFAULT_PROFILE_ID}",
            "sourceTrusted": False,
            "requiresReview": True,
            "freezeBlocked": True,
        }
        for family in EXTERNAL_DIALECT_FAMILIES
    ]
    body = {
        "schemaVersion": EXTERNAL_DIALECT_REGISTRY_SCHEMA,
        "enabledByDefault": False,
        "sourceTrusted": False,
        "families": list(EXTERNAL_DIALECT_FAMILIES),
        "profiles": profiles,
    }
    return {**body, "registryDigest": canonical_digest(body)}


def validate_external_dialect_profile(profile: dict[str, Any]) -> dict[str, Any]:
    validation = validate_dialect_profile(profile)
    blockers = list(validation["blockers"])
    if profile.get("family") not in EXTERNAL_DIALECT_FAMILIES:
        blockers.append({"code": "external-dialect-family-invalid", "family": profile.get("family")})
    profile_id = profile.get("profileId")
    if not isinstance(profile_id, str) or not _PROFILE_RE.match(profile_id):
        blockers.append({"code": "external-dialect-profile-id-invalid"})
    body = {
        **validation,
        "status": "PASS" if not blockers else "FAIL",
        "family": profile.get("family"),
        "profileId": profile.get("profileId"),
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest({key: value for key, value in body.items() if key != "validationDigest"})}


def require_external_profile_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("external-dialect-profile-validation-failed", "external dialect profile validation failed", {"validation": validation})
    return validation


def _validate_family(family: str) -> None:
    if family not in EXTERNAL_DIALECT_FAMILIES:
        raise LifecycleError("external-dialect-family-invalid", "external dialect family is unsupported", {"family": family})


def _validate_profile_id(profile_id: str) -> None:
    if not isinstance(profile_id, str) or not _PROFILE_RE.match(profile_id):
        raise LifecycleError("external-dialect-profile-id-invalid", "external dialect profile id is invalid")


def _markers_for_family(family: str) -> list[str]:
    if family == "workflow":
        return ["workflow", "steps", "jobs", "validation", "checks"]
    return ["agent", "role", "tools", "policy", "environment"]


def _mapping_for_family(family: str) -> dict[str, Any]:
    if family == "workflow":
        return {
            "title": ["name", "title", "workflow"],
            "requirements": ["steps", "jobs"],
            "validationHints": ["validation", "validations", "checks"],
            "candidateStatus": "DRAFT",
        }
    return {
        "title": ["name", "title", "agent"],
        "requirements": ["role", "instructions", "policies", "rules"],
        "hostLocalHints": ["provider", "model", "auth", "environment", "tools"],
        "candidateStatus": "DRAFT",
    }
