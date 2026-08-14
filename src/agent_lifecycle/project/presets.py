"""Deterministic built-in workflow presets for project profile drafts."""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    load_json_object,
)
from agent_lifecycle.contracts.project_profile_preset_schemas import (
    PROJECT_PROFILE_PRESET_LIST_SCHEMA,
    PROJECT_PROFILE_PRESET_OPERATION_SCHEMA,
    PROJECT_PROFILE_PRESET_RENDER_SCHEMA,
    PROJECT_PROFILE_PRESET_SCHEMA,
    PROJECT_PROFILE_PRESET_VALIDATION_SCHEMA,
)
from agent_lifecycle.contracts.project_profile_schemas import (
    PROJECT_PROFILE_MODEL_CLASSES,
    PROJECT_PROFILE_MODES,
    PROJECT_PROFILE_PRESET_AUTHORITIES,
    PROJECT_PROFILE_PRESET_IDS,
    PROJECT_PROFILE_RISKS,
    PROJECT_PROFILE_STAGES,
)
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS
from agent_lifecycle.policy.thread_bridge import build_default_thread_bridge_policy
from agent_lifecycle.project.profile import (
    profile_field_is_explicit,
    validate_stage_settings,
)

PRESET_DIRECTORY = Path("profiles/project-workflow-presets")
MAX_PRESET_BYTES = 32768
MAX_PRESETS = 8
_URL = re.compile(r"(?:https?|file)://", re.IGNORECASE)
_ABSOLUTE_PATH = re.compile(r"^(?:/|[A-Za-z]:[\\/])")
_FORBIDDEN_KEYS = {
    "account",
    "apikey",
    "argv",
    "authorization",
    "command",
    "commands",
    "credential",
    "credentials",
    "executable",
    "filepath",
    "host",
    "localpath",
    "model",
    "modelid",
    "modelname",
    "network",
    "password",
    "path",
    "prompt",
    "provider",
    "providername",
    "script",
    "secret",
    "shell",
    "subprocess",
    "token",
    "url",
}
_FORBIDDEN_TEXT = re.compile(
    r"(?:^|\s)(?:bash|cmd|curl|git|npm|pip|pnpm|powershell|python(?:3)?|sh|wget|yarn)\s+|"
    r"(?:^|\s)(?:execute|invoke|launch|run)\s+(?:a\s+)?(?:command|script|process)\b",
    re.IGNORECASE,
)


def list_project_presets(*, project_root: Path | None = None) -> dict[str, Any]:
    """Return stable summaries of all built-in presets."""

    summaries = []
    for preset_id in PROJECT_PROFILE_PRESET_IDS:
        preset = load_project_preset(preset_id, project_root=project_root)
        summaries.append(_summary(preset))
    body = {
        "schemaVersion": PROJECT_PROFILE_PRESET_LIST_SCHEMA,
        "status": "PASS",
        "presets": summaries,
        "productionPromotionClaimed": False,
    }
    return {**body, "resultDigest": canonical_digest(body)}


def inspect_project_preset(preset_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    preset = load_project_preset(preset_id, project_root=project_root)
    validation = validate_project_preset(preset)
    _require_valid(validation)
    body = {
        "schemaVersion": PROJECT_PROFILE_PRESET_OPERATION_SCHEMA,
        "status": "PASS",
        "operation": "inspect",
        "preset": preset,
        "validation": validation,
        "productionPromotionClaimed": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
    }
    return {**body, "resultDigest": canonical_digest(body)}


def validate_project_preset(preset: dict[str, Any]) -> dict[str, Any]:
    """Validate one preset as bounded, provider-neutral data."""

    blockers: list[dict[str, Any]] = []
    preset_id = preset.get("presetId") if isinstance(preset, dict) else None
    if not isinstance(preset, dict):
        blockers.append({"code": "preset-not-object"})
        return _validation(None, None, blockers)
    if preset.get("schemaVersion") != PROJECT_PROFILE_PRESET_SCHEMA:
        blockers.append({"code": "preset-schema-invalid"})
    if preset_id not in PROJECT_PROFILE_PRESET_IDS:
        blockers.append({"code": "preset-id-invalid", "presetId": preset_id})
    for key in ("presetVersion", "title", "description"):
        if not isinstance(preset.get(key), str) or not preset[key].strip():
            blockers.append({"code": "preset-field-required", "field": key})
    if preset.get("defaultMode") not in PROJECT_PROFILE_MODES:
        blockers.append({"code": "preset-mode-invalid"})
    if preset.get("defaultRisk") not in PROJECT_PROFILE_RISKS:
        blockers.append({"code": "preset-risk-invalid"})
    if preset.get("reviewMesh") not in {"off", *REVIEW_MESH_MODE_IDS}:
        blockers.append({"code": "preset-review-mesh-invalid"})
    if preset.get("implementationAuthority") not in PROJECT_PROFILE_PRESET_AUTHORITIES:
        blockers.append({"code": "preset-implementation-authority-invalid"})
    if preset.get("source") != "built-in":
        blockers.append({"code": "preset-source-invalid"})
    if preset.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "preset-production-claim"})
    if "qualityFloor" in preset:
        blockers.append({"code": "preset-quality-floor-authority"})
    _reject_unsafe_values(preset, blockers)
    if len(canonical_bytes(preset)) > MAX_PRESET_BYTES:
        blockers.append({"code": "preset-size-limit", "limit": MAX_PRESET_BYTES})

    stages = preset.get("stages")
    if not isinstance(stages, dict) or not stages:
        blockers.append({"code": "preset-stages-required"})
        stages = {}
    if len(stages) > len(PROJECT_PROFILE_STAGES):
        blockers.append({"code": "preset-stage-limit"})
    for stage, settings in stages.items():
        if stage not in PROJECT_PROFILE_STAGES:
            blockers.append({"code": "preset-stage-invalid", "stage": stage})
            continue
        try:
            validate_stage_settings(stage, settings)
        except LifecycleError as exc:
            blockers.append({"code": exc.code, "stage": stage, "message": exc.message})
            continue
        if not isinstance(settings, dict):
            continue
        for required in ("mode", "risk", "modelClass", "reviewMesh", "maxAttempts", "maxInvocations", "maxWallSeconds"):
            if required not in settings:
                blockers.append({"code": "preset-stage-field-required", "stage": stage, "field": required})
        if settings.get("modelClass") not in PROJECT_PROFILE_MODEL_CLASSES:
            blockers.append({"code": "preset-stage-model-class-invalid", "stage": stage})
        if settings.get("reviewMesh") not in {"off", *REVIEW_MESH_MODE_IDS}:
            blockers.append({"code": "preset-stage-review-mesh-invalid", "stage": stage})

    authority = preset.get("implementationAuthority")
    if authority == "excluded" and "implementation" in stages:
        blockers.append({"code": "preset-implementation-not-excluded"})
    if authority == "requires-frozen-plan" and "implementation" not in stages:
        blockers.append({"code": "preset-implementation-stage-missing"})

    expected_digest = preset_digest(preset)
    if preset.get("presetDigest") != expected_digest:
        blockers.append({"code": "preset-digest-mismatch", "expected": expected_digest})
    return _validation(preset_id, expected_digest, blockers)


def render_project_preset(
    preset_id: str,
    *,
    output_path: Path,
    project_root: Path,
    profile_id: str | None = None,
    default_adapter: str | None = None,
) -> dict[str, Any]:
    """Render a valid project-profile draft to an explicit path."""

    if not output_path.is_absolute():
        output_path = project_root / output_path
    root = project_root.resolve()
    parent = output_path.parent.resolve(strict=False)
    if not _is_relative_to(parent, root):
        raise LifecycleError("preset-output-escape", "preset output must stay inside the project root")
    if output_path.exists() and output_path.is_symlink():
        raise LifecycleError("preset-output-symlink", "preset output must not be a symlink")
    preset = load_project_preset(preset_id, project_root=project_root)
    validation = validate_project_preset(preset)
    _require_valid(validation)
    profile = build_preset_profile_draft(
        preset,
        profile_id=profile_id,
        default_adapter=default_adapter,
        project_root=project_root,
    )
    from agent_lifecycle.contracts import write_json_create

    try:
        data = write_json_create(output_path, profile)
    except FileExistsError as exc:
        raise LifecycleError("preset-output-exists", "preset output already exists", {"path": str(output_path)}) from exc
    body = {
        "schemaVersion": PROJECT_PROFILE_PRESET_RENDER_SCHEMA,
        "status": "PASS",
        "operation": "render",
        "presetId": preset_id,
        "outputPath": _display_path(output_path, project_root),
        "profile": profile,
        "profileDigest": canonical_digest(profile),
        "explicitOutputPath": True,
        "bytesWritten": len(data),
        "productionPromotionClaimed": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def merge_preset_defaults(
    profile: dict[str, Any] | None,
    preset: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Apply preset defaults below explicit project-profile values."""

    preset_validation = validate_project_preset(preset)
    _require_valid(preset_validation)
    preset_profile = build_preset_profile_draft(preset, project_root=project_root)
    if profile is None:
        return preset_profile

    from agent_lifecycle.project.profile import normalize_project_profile

    existing = normalize_project_profile(profile, project_root=project_root)
    combined = copy.deepcopy(preset_profile)
    combined["profileId"] = existing["profileId"]
    if profile_field_is_explicit(existing, "defaultAdapter"):
        combined["defaultAdapter"] = existing["defaultAdapter"]
    if profile_field_is_explicit(existing, "defaultMode"):
        combined["defaultMode"] = existing["defaultMode"]
    if profile_field_is_explicit(existing, "defaultRisk"):
        combined["defaultRisk"] = existing["defaultRisk"]
    combined["policies"] = copy.deepcopy(existing.get("policies", {}))
    combined["stages"] = copy.deepcopy(preset_profile.get("stages", {}))
    for stage, settings in existing.get("stages", {}).items():
        combined["stages"].setdefault(stage, {}).update(copy.deepcopy(settings))
    combined["threadBridge"] = copy.deepcopy(existing.get("threadBridge", build_default_thread_bridge_policy()))
    if "principles" in existing:
        combined["principles"] = copy.deepcopy(existing["principles"])
    combined["productionPromotionClaimed"] = False
    return combined


def build_preset_profile_draft(
    preset: dict[str, Any],
    *,
    profile_id: str | None = None,
    default_adapter: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    validation = validate_project_preset(preset)
    _require_valid(validation)
    from agent_lifecycle.project.profile import validate_project_profile

    profile = {
        "schemaVersion": "agent-project-workflow-profile.v1",
        "profileId": profile_id or f"preset-{preset['presetId']}",
        "defaultAdapter": default_adapter,
        "defaultMode": preset["defaultMode"],
        "defaultRisk": preset["defaultRisk"],
        "policies": {},
        "stages": copy.deepcopy(preset["stages"]),
        "threadBridge": build_default_thread_bridge_policy(),
        "productionPromotionClaimed": False,
    }
    validate_project_profile(profile, project_root=project_root)
    return profile


def load_project_preset(preset_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    if preset_id not in PROJECT_PROFILE_PRESET_IDS:
        raise LifecycleError("preset-unknown", "unknown built-in workflow preset", {"presetId": preset_id})
    for path in _preset_paths(project_root):
        if path.is_file():
            payload = load_json_object(path.read_bytes(), label="workflow preset")
            if payload.get("presetId") == preset_id:
                validation = validate_project_preset(payload)
                _require_valid(validation)
                return payload
    raise LifecycleError("preset-missing", "built-in workflow preset is not installed", {"presetId": preset_id})


def preset_digest(preset: dict[str, Any]) -> str:
    return canonical_digest({key: value for key, value in preset.items() if key != "presetDigest"})


def _preset_paths(project_root: Path | None) -> list[Path]:
    # Preset ids are built-in release data. A consuming project must not be
    # able to shadow a shipped preset by placing a same-named JSON file in its
    # own tree.
    roots = [Path(__file__).resolve().parents[3], Path(sys.prefix).resolve()]
    result: list[Path] = []
    for root in roots:
        candidate = root / PRESET_DIRECTORY
        if candidate not in result:
            result.append(candidate)
    return [directory / f"{preset_id}.v1.json" for directory in result for preset_id in PROJECT_PROFILE_PRESET_IDS]


def _summary(preset: dict[str, Any]) -> dict[str, Any]:
    return {
        "presetId": preset["presetId"],
        "presetVersion": preset["presetVersion"],
        "title": preset["title"],
        "defaultMode": preset["defaultMode"],
        "defaultRisk": preset["defaultRisk"],
        "reviewMesh": preset["reviewMesh"],
        "implementationAuthority": preset["implementationAuthority"],
    }


def _validation(preset_id: str | None, digest: str | None, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": PROJECT_PROFILE_PRESET_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "presetId": preset_id,
        "presetDigest": digest,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _require_valid(validation: dict[str, Any]) -> None:
    if validation.get("status") != "PASS":
        raise LifecycleError("preset-validation-failed", "workflow preset failed validation", {"validation": validation})


def _reject_unsafe_values(value: Any, blockers: list[dict[str, Any]], *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in _FORBIDDEN_KEYS:
                blockers.append({"code": "preset-sensitive-field", "path": f"{path}.{key}".strip(".")})
            _reject_unsafe_values(nested, blockers, path=f"{path}.{key}".strip("."))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_unsafe_values(nested, blockers, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if _URL.search(value) or _ABSOLUTE_PATH.match(value):
            blockers.append({"code": "preset-unsafe-reference", "path": path})
        if _FORBIDDEN_TEXT.search(value):
            blockers.append({"code": "preset-executable-text", "path": path})


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "<project>"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
