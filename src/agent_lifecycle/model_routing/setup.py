"""Pure setup proposal validation; callers own discovery and safe persistence."""

from __future__ import annotations

import copy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.model_routing.stage_bindings import closed_object, validate_binding_refs, validate_stage_registry


def setup_proposal(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "schemaVersion": "agent-model-setup-proposal.v1",
            "status": "MISSING_INPUT",
            "requiredFields": ["projectProfile", "registry"],
            "scope": "project",
            "modelCallsStarted": False,
        }
    closed_object(payload, {"projectProfile", "registry"})
    registry = payload["registry"]
    validation = validate_stage_registry(registry)
    profile = payload["projectProfile"]
    if not isinstance(profile, dict):
        raise LifecycleError("model-setup-profile-invalid", "projectProfile must be an object")
    stages = profile.get("stages", {})
    if not isinstance(stages, dict) or any(not isinstance(value, dict) for value in stages.values()):
        raise LifecycleError("model-setup-profile-invalid", "stages and stage settings must be objects")
    for settings in stages.values():
        if "executionBindingRefs" in settings:
            refs = validate_binding_refs(settings["executionBindingRefs"])
            if set(refs) - set(registry["bindings"]):
                raise LifecycleError("stage-binding-missing", "stage references an absent registry entry")
    body = {
        "schemaVersion": "agent-model-setup-proposal.v1",
        "status": "READY",
        "scope": "project",
        "visibility": "LOCAL_ONLY",
        "projectProfile": copy.deepcopy(profile),
        "registry": copy.deepcopy(registry),
        **validation,
        "modelCallsStarted": False,
        "applied": False,
        "qualificationStatus": "UNVERIFIED",
    }
    return {**body, "proposalDigest": canonical_digest(body)}
