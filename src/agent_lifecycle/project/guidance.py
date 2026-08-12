"""Bounded projections for host-owned project stage guidance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.project_profile_schemas import PROJECT_PROFILE_STAGES
from agent_lifecycle.project.profile import MAX_GUIDANCE_BYTES, validate_stage_settings


def build_stage_guidance_projection(
    effective_profile: dict[str, Any],
    *,
    stage: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Project stage settings into a non-executable host presentation hint."""

    if stage not in PROJECT_PROFILE_STAGES:
        raise LifecycleError("project-profile-stage-unsupported", "stage name is not canonical", {"stage": stage})
    stages = effective_profile.get("stages") if isinstance(effective_profile.get("stages"), dict) else {}
    settings = stages.get(stage, {})
    checked = validate_stage_settings(stage, settings, project_root=project_root)
    guidance_ref = checked.get("guidanceRef")
    guidance = {
        "stage": stage,
        "guidanceRef": guidance_ref,
        "guidancePresent": False,
        "guidanceBytes": 0,
        "guidanceExecutable": False,
        "systemPromptAuthority": False,
        "hostOwned": True,
    }
    if guidance_ref and project_root is not None:
        path = project_root.resolve() / guidance_ref
        try:
            if path.is_file() and not path.is_symlink():
                size = path.stat().st_size
                if size > MAX_GUIDANCE_BYTES:
                    raise LifecycleError(
                        "project-profile-guidance-too-large",
                        "guidance file exceeds the configured byte limit",
                        {"stage": stage, "bytes": size},
                    )
                guidance["guidancePresent"] = True
                guidance["guidanceBytes"] = size
        except OSError as exc:
            raise LifecycleError("project-profile-guidance-read-failed", "guidance metadata cannot be read") from exc
    return {
        "schemaVersion": "agent-project-stage-guidance-projection.v1",
        "profileDigest": effective_profile.get("effectiveProfileDigest"),
        "stage": stage,
        "settings": checked,
        "guidance": guidance,
        "productionPromotionClaimed": False,
    }
