"""Validation and loading for project-local workflow profiles."""

from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object
from agent_lifecycle.contracts.paths import MAX_REPO_PATH_BYTES, normalize_repo_path
from agent_lifecycle.contracts.project_profile_schemas import (
    PROFILE_POLICY_KEYS,
    PROJECT_PROFILE_MODEL_CLASSES,
    PROJECT_PROFILE_MODES,
    PROJECT_PROFILE_RISKS,
    PROJECT_PROFILE_SCHEMA,
    PROJECT_PROFILE_STAGES,
    STAGE_SETTING_KEYS,
)
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS
from agent_lifecycle.policy.thread_bridge import (
    build_default_thread_bridge_policy,
    normalize_thread_bridge_policy,
    validate_thread_bridge_policy,
)

MAX_PROFILE_BYTES = 65536
MAX_GUIDANCE_BYTES = 16384
MAX_POLICY_REFERENCES = 8
MAX_STAGE_SETTINGS = 32
MAX_PROFILE_ID_BYTES = 128
PROJECT_PROFILE_RELATIVE_PATH = ".alk/project-profile.json"

_PROFILE_KEYS = {
    "schemaVersion",
    "profileId",
    "defaultAdapter",
    "defaultMode",
    "defaultRisk",
    "policies",
    "stages",
    "principles",
    "threadBridge",
    "productionPromotionClaimed",
}
_FORBIDDEN_KEYS = {
    "account",
    "accountid",
    "apikey",
    "apikeyvalue",
    "auth",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "password",
    "prompt",
    "prompttemplate",
    "provider",
    "providerid",
    "providermodel",
    "providername",
    "secret",
    "secrets",
    "systemprompt",
    "token",
    "tokenvalue",
}
_POLICY_REFERENCE_KEYS = set(PROFILE_POLICY_KEYS)
_REVIEW_MESH_VALUES = {"off", *REVIEW_MESH_MODE_IDS}


def load_project_profile(path: Path, *, project_root: Path | None = None) -> dict[str, Any]:
    """Load and validate a contained JSON profile without executing references."""

    root = (project_root or Path.cwd()).resolve()
    candidate = path if path.is_absolute() else root / path
    _require_contained_file(candidate, root, label="project profile")
    try:
        size = candidate.stat().st_size
    except OSError as exc:
        raise LifecycleError("project-profile-read-failed", "project profile cannot be read", {"path": str(path)}) from exc
    if size > MAX_PROFILE_BYTES:
        raise LifecycleError(
            "project-profile-too-large",
            f"project profile exceeds {MAX_PROFILE_BYTES} bytes",
            {"bytes": size},
        )
    try:
        payload = load_json_object(candidate.read_bytes(), label="project profile")
    except OSError as exc:
        raise LifecycleError("project-profile-read-failed", "project profile cannot be read", {"path": str(path)}) from exc
    return normalize_project_profile(payload, project_root=root, profile_path=candidate)


def build_default_project_profile() -> dict[str, Any]:
    """Return the minimal profile written by ``project profile init``."""

    return {
        "schemaVersion": PROJECT_PROFILE_SCHEMA,
        "profileId": "project-default",
        "defaultAdapter": None,
        "defaultMode": "auto",
        "defaultRisk": "auto",
        "policies": {},
        "stages": {},
        "threadBridge": build_default_thread_bridge_policy(),
        "productionPromotionClaimed": False,
    }


def normalize_project_profile(
    profile: dict[str, Any],
    *,
    project_root: Path | None = None,
    profile_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a profile and return a detached, canonical default layer."""

    validate_project_profile(profile, project_root=project_root, profile_path=profile_path)
    normalized = copy.deepcopy(profile)
    normalized.setdefault("policies", {})
    normalized.setdefault("stages", {})
    if "principles" in normalized:
        normalized["principles"] = _validate_principles_reference(
            normalized["principles"], project_root=project_root
        )
    normalized["threadBridge"] = normalize_thread_bridge_policy(normalized.get("threadBridge"))
    normalized.setdefault("productionPromotionClaimed", False)
    return normalized


def validate_project_profile(
    profile: dict[str, Any],
    *,
    project_root: Path | None = None,
    profile_path: Path | None = None,
) -> dict[str, Any]:
    """Validate portable fields, stage bounds and repository-relative references."""

    if not isinstance(profile, dict):
        raise LifecycleError("invalid-project-profile", "project profile must be an object")
    _reject_forbidden_keys(profile)
    unknown = sorted(set(profile) - _PROFILE_KEYS)
    if unknown:
        raise LifecycleError("project-profile-field-unsupported", "project profile contains unsupported fields", {"fields": unknown})
    if profile.get("schemaVersion") != PROJECT_PROFILE_SCHEMA:
        raise LifecycleError("invalid-project-profile", "unsupported project profile schemaVersion")
    profile_id = _required_string(profile, "profileId")
    if len(profile_id.encode("utf-8")) > MAX_PROFILE_ID_BYTES:
        raise LifecycleError("project-profile-limit", "profileId exceeds the configured byte limit")
    default_adapter = profile.get("defaultAdapter")
    if default_adapter is not None and (not isinstance(default_adapter, str) or not default_adapter.strip()):
        raise LifecycleError("project-profile-adapter-invalid", "defaultAdapter must be a non-empty string or null")
    _require_enum(profile, "defaultMode", PROJECT_PROFILE_MODES)
    _require_enum(profile, "defaultRisk", PROJECT_PROFILE_RISKS)
    if profile.get("productionPromotionClaimed", False) is not False:
        raise LifecycleError("project-profile-production-claim", "project profile cannot claim production promotion")
    if "principles" in profile:
        _validate_principles_reference(profile["principles"], project_root=project_root)

    policies = profile.get("policies", {})
    if not isinstance(policies, dict):
        raise LifecycleError("project-profile-policies-invalid", "policies must be an object")
    unknown_policies = sorted(set(policies) - _POLICY_REFERENCE_KEYS)
    if unknown_policies:
        raise LifecycleError("project-profile-policy-field-unsupported", "unsupported policy reference", {"fields": unknown_policies})
    non_empty_references = 0
    for key in PROFILE_POLICY_KEYS:
        value = policies.get(key)
        if value is None:
            continue
        non_empty_references += 1
        _validate_reference(value, field=f"policies.{key}", project_root=project_root, allow_alk=key == "hostModelProfile")
    if non_empty_references > MAX_POLICY_REFERENCES:
        raise LifecycleError("project-profile-policy-limit", "too many policy references", {"limit": MAX_POLICY_REFERENCES})

    stages = profile.get("stages", {})
    if not isinstance(stages, dict):
        raise LifecycleError("project-profile-stages-invalid", "stages must be an object")
    unknown_stages = sorted(set(stages) - set(PROJECT_PROFILE_STAGES))
    if unknown_stages:
        raise LifecycleError("project-profile-stage-unsupported", "stage name is not canonical", {"stages": unknown_stages})
    if len(stages) > len(PROJECT_PROFILE_STAGES):
        raise LifecycleError("project-profile-stage-limit", "too many stage settings")
    for stage, settings in stages.items():
        _validate_stage_settings(stage, settings, project_root=project_root)
    thread_bridge = profile.get("threadBridge")
    if thread_bridge is not None:
        validate_thread_bridge_policy(thread_bridge)
    return {
        "status": "PASS",
        "schemaVersion": PROJECT_PROFILE_SCHEMA,
        "profileId": profile_id,
        "stageCount": len(stages),
        "policyReferenceCount": non_empty_references,
        "profileDigest": project_profile_digest(profile),
        "productionPromotionClaimed": False,
    }


def project_profile_digest(profile: dict[str, Any]) -> str:
    """Return a deterministic digest without mutating the input profile."""

    return canonical_digest(profile)


def validate_stage_settings(
    stage: str,
    settings: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Public helper used by the merge layer for bounded CLI stage overrides."""

    _validate_stage_settings(stage, settings, project_root=project_root)
    return copy.deepcopy(settings)


def _validate_stage_settings(stage: str, settings: Any, *, project_root: Path | None) -> None:
    if stage not in PROJECT_PROFILE_STAGES:
        raise LifecycleError("project-profile-stage-unsupported", "stage name is not canonical", {"stage": stage})
    if not isinstance(settings, dict):
        raise LifecycleError("project-profile-stage-invalid", "stage settings must be an object", {"stage": stage})
    unknown = sorted(set(settings) - set(STAGE_SETTING_KEYS))
    if unknown:
        raise LifecycleError("project-profile-stage-field-unsupported", "unsupported stage setting", {"stage": stage, "fields": unknown})
    if len(settings) > MAX_STAGE_SETTINGS:
        raise LifecycleError("project-profile-stage-limit", "stage settings exceed the configured limit", {"stage": stage})
    if "mode" in settings:
        _require_value_enum(settings["mode"], "mode", PROJECT_PROFILE_MODES, stage=stage)
    if "risk" in settings:
        _require_value_enum(settings["risk"], "risk", PROJECT_PROFILE_RISKS, stage=stage)
    if "modelClass" in settings:
        _require_value_enum(settings["modelClass"], "modelClass", PROJECT_PROFILE_MODEL_CLASSES, stage=stage)
    if "reviewMesh" in settings:
        _require_value_enum(settings["reviewMesh"], "reviewMesh", _REVIEW_MESH_VALUES, stage=stage)
    _bounded_int(settings, "minReviewers", minimum=0, maximum=16, stage=stage)
    _bounded_int(settings, "maxAttempts", minimum=1, maximum=10, stage=stage)
    _bounded_int(settings, "maxInvocations", minimum=1, maximum=100, stage=stage)
    _bounded_int(settings, "maxWallSeconds", minimum=1, maximum=86400, stage=stage)
    if "guidanceRef" in settings:
        _validate_reference(settings["guidanceRef"], field=f"stages.{stage}.guidanceRef", project_root=project_root, allow_alk=False)


def _validate_reference(value: Any, *, field: str, project_root: Path | None, allow_alk: bool) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("project-profile-reference-invalid", f"{field} must be a relative path")
    try:
        normalized = normalize_repo_path(value, label=field)
    except LifecycleError as exc:
        raise LifecycleError("project-profile-reference-invalid", exc.message, {"field": field}) from exc
    if normalized.startswith(".alk/") and not allow_alk:
        raise LifecycleError(
            "project-profile-reference-boundary",
            f"{field} cannot use the .alk host-local exception",
            {"field": field},
        )
    if project_root is not None:
        root = project_root.resolve()
        candidate = root.joinpath(PurePosixPath(normalized))
        resolved = candidate.resolve(strict=False)
        if not _is_relative_to(resolved, root):
            raise LifecycleError("project-profile-reference-escape", f"{field} escapes the project root", {"field": field})
        _reject_symlink_components(root, candidate, field=field)
    return normalized


def _validate_principles_reference(value: Any, *, project_root: Path | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("project-profile-principles-invalid", "principles must be an object")
    if value.get("sourceOfTruth") is not False:
        raise LifecycleError(
            "project-profile-principles-authority",
            "project principles cannot become the source of truth",
        )
    path = _validate_reference(value.get("path"), field="principles.path", project_root=project_root, allow_alk=False)
    digest = value.get("digest")
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise LifecycleError("project-profile-principles-digest-invalid", "principles.digest must be a lowercase SHA-256 digest")
    return {"path": path, "digest": digest, "sourceOfTruth": False}


def _require_contained_file(path: Path, root: Path, *, label: str) -> None:
    if path.is_symlink():
        raise LifecycleError("project-profile-path-symlink", f"{label} must not be a symlink")
    resolved = path.resolve(strict=False)
    if not _is_relative_to(resolved, root):
        raise LifecycleError("project-profile-path-escape", f"{label} escapes the project root")
    if not path.exists() or not path.is_file():
        raise LifecycleError("project-profile-missing", f"{label} must be a regular file")
    _reject_symlink_components(root, path, field=label)


def _reject_symlink_components(root: Path, candidate: Path, *, field: str) -> None:
    root_resolved = root.resolve()
    current = candidate.absolute()
    while True:
        if current.resolve(strict=False) == root_resolved:
            break
        if current.is_symlink():
            raise LifecycleError("project-profile-reference-symlink", f"{field} contains a symlink component", {"field": field})
        if current.parent == current:
            raise LifecycleError("project-profile-reference-escape", f"{field} escapes the project root", {"field": field})
        current = current.parent


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str):
                compact = "".join(character for character in key.lower() if character.isalnum())
                if compact in _FORBIDDEN_KEYS:
                    raise LifecycleError("project-profile-sensitive-field", "project profile contains a sensitive field", {"field": key})
            _reject_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_keys(nested)


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LifecycleError("project-profile-field-invalid", f"{key} must be a non-empty string")
    return value


def _require_enum(payload: dict[str, Any], key: str, allowed: Any) -> str:
    value = payload.get(key)
    return _require_value_enum(value, key, allowed)


def _require_value_enum(value: Any, key: str, allowed: Any, *, stage: str | None = None) -> str:
    if value not in allowed:
        details = {"field": key, "value": value}
        if stage is not None:
            details["stage"] = stage
        raise LifecycleError("project-profile-value-invalid", f"{key} has an unsupported value", details)
    return value


def _bounded_int(payload: dict[str, Any], key: str, *, minimum: int, maximum: int, stage: str) -> None:
    if key not in payload:
        return
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise LifecycleError(
            "project-profile-limit-invalid",
            f"{stage}.{key} must be an integer between {minimum} and {maximum}",
            {"stage": stage, "field": key},
        )
