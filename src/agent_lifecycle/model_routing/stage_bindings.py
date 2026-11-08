"""Pure validation and portable projections for local stage binding references."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, normalize_repo_path
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.execution_strategy_schemas import STAGE_BINDING_DIGEST_FIELDS
from agent_lifecycle.contracts.launch_qualification import QUALIFICATION_RECEIPT_SCHEMA
from agent_lifecycle.contracts.local_launch_validation import validate_local_launch_profile
from agent_lifecycle.contracts.model_classes import ALLOWED_MODEL_CLASSES
from agent_lifecycle.contracts.project_profile_schemas import PROJECT_PROFILE_STAGES
from agent_lifecycle.model_routing.profiles import validate_host_model_profile

REGISTRY_SCHEMA = "agent-local-stage-bindings.v1"
MAX_REGISTRY_BYTES = 32768
MAX_BINDINGS = 32
MAX_STAGE_BINDINGS = 3
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)
_MODE_STAGE = {
    "auto": "intake",
    "research": "research",
    "plan": "planning",
    "review": "review",
    "implement": "implementation",
}


def local_reference(value: Any, *, model: bool = False) -> dict[str, Any]:
    """Validate a closed digest reference without opening its local file."""
    keys = {"path", "sha256", "modelClass"} if model else {"path", "sha256"}
    closed_object(value, keys)
    path = normalize_repo_path(value["path"], label="stage binding reference")
    if not path.startswith(".alk/host-launch/") or not _SHA.fullmatch(str(value["sha256"])):
        raise LifecycleError(
            "stage-binding-reference-invalid", "references require a local contained path and raw SHA256"
        )
    if model and (value["modelClass"] not in ALLOWED_MODEL_CLASSES or value["modelClass"] == "no-model"):
        raise LifecycleError("stage-binding-class-invalid", "a host binding requires a routable neutral class")
    return dict(value)


def closed_object(value: Any, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise LifecycleError(
            "stage-binding-fields-invalid", "local stage binding object has missing or unsupported fields"
        )


def validate_binding_refs(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= MAX_STAGE_BINDINGS
        or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise LifecycleError("stage-binding-order-invalid", "stage order requires one to three unique direct IDs")
    return list(value)


def validate_stage_registry(registry: dict[str, Any]) -> dict[str, Any]:
    closed_object(registry, {"schemaVersion", "bindings"})
    entries = registry["bindings"]
    if (
        registry["schemaVersion"] != REGISTRY_SCHEMA
        or not isinstance(entries, dict)
        or not 1 <= len(entries) <= MAX_BINDINGS
    ):
        raise LifecycleError("stage-binding-registry-invalid", "registry requires one to 32 local bindings")
    for binding_id, entry in entries.items():
        if not isinstance(binding_id, str) or not _ID.fullmatch(binding_id):
            raise LifecycleError("stage-binding-id-invalid", "invalid local binding ID")
        validate_stage_binding(entry)
    return {"registryDigest": canonical_digest(registry), "bindingCount": len(entries)}


def validate_stage_binding(entry: dict[str, Any], *, host_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    closed_object(
        entry,
        {
            "adapterId",
            "hostModelProfile",
            "launchProfile",
            "hostParameters",
            "parameterSupport",
            "qualificationEvidence",
        },
    )
    if not isinstance(entry["adapterId"], str) or not _ID.fullmatch(entry["adapterId"]):
        raise LifecycleError("stage-binding-adapter-invalid", "invalid adapter ID")
    model = local_reference(entry["hostModelProfile"], model=True)
    for key in ("launchProfile", "qualificationEvidence"):
        local_reference(entry[key])
    closed_object(entry["hostParameters"], {"reasoningEffort"})
    support = entry["parameterSupport"]
    closed_object(support, {"allowedEfforts", "evidence"})
    local_reference(support["evidence"])
    efforts = support["allowedEfforts"]
    if (
        not isinstance(efforts, list)
        or not 1 <= len(efforts) <= 16
        or any(not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", item) for item in efforts)
        or len(set(efforts)) != len(efforts)
        or entry["hostParameters"]["reasoningEffort"] not in efforts
    ):
        raise LifecycleError("stage-binding-effort-unsupported", "explicit effort must be declared supported")
    if host_profile is not None:
        checked = validate_host_model_profile(host_profile)
        if checked["host"] != entry["adapterId"] or model["modelClass"] not in checked["classes"]:
            raise LifecycleError("stage-binding-host-mismatch", "host profile, adapter and model class must match")
    return {"bindingDigest": canonical_digest(entry), "modelClass": model["modelClass"]}


def select_stage(mode: str, stage: str | None = None) -> str:
    selected = stage or _MODE_STAGE.get(mode)
    if selected not in PROJECT_PROFILE_STAGES:
        raise LifecycleError("stage-binding-stage-invalid", "unknown lifecycle stage")
    if stage in {"audit", "finalization"}:
        if mode != "review":
            raise LifecycleError("stage-binding-stage-mode", "audit and finalization require review mode")
    elif stage is not None and selected != _MODE_STAGE.get(mode):
        raise LifecycleError("stage-binding-stage-mode", "explicit stage does not match lifecycle mode")
    return str(selected)


def ordered_stage_refs(profile: dict[str, Any], stage: str, binding_id: str | None = None) -> list[str]:
    refs = validate_binding_refs(profile.get("stages", {}).get(stage, {}).get("executionBindingRefs"))
    if binding_id is not None:
        if binding_id not in refs:
            raise LifecycleError(
                "stage-binding-not-approved", "explicit binding must be a member of the approved stage list"
            )
        return [binding_id]
    return refs


def portable_selection(selection: dict[str, Any]) -> dict[str, Any]:
    """Allowlist the projection; local IDs, paths and host literals never escape."""
    keys = (
        "stage",
        "modelClass",
        "selectedBindingDigest",
        "orderedBindingDigests",
        "registryDigest",
        "projectProfileDigest",
        "effectiveProfileDigest",
        "sourceRevision",
        "executableDigest",
        "launchProfileDigest",
        "invocationDigest",
        "reasonCodes",
        "status",
        "winningSource",
    )
    return {key: selection[key] for key in keys if key in selection}


def validate_neutral_stage_binding(value: Any) -> dict[str, Any]:
    closed_object(value, {"stage", "modelClass", *STAGE_BINDING_DIGEST_FIELDS})
    if value["stage"] not in PROJECT_PROFILE_STAGES or value["modelClass"] not in ALLOWED_MODEL_CLASSES - {"no-model"}:
        raise LifecycleError("stage-binding-neutral-invalid", "stage binding requires a known stage and model class")
    if any(not isinstance(value[key], str) or not _SHA.fullmatch(value[key]) for key in STAGE_BINDING_DIGEST_FIELDS):
        raise LifecycleError("stage-binding-neutral-invalid", "stage binding digests must be exact lowercase SHA256")
    return dict(value)


def read_binding_reference(root: Path, reference: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    local_reference(reference, model="modelClass" in reference)
    raw = read_authority_bytes(root / reference["path"], root=root, max_bytes=MAX_REGISTRY_BYTES)
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise LifecycleError("stage-binding-reference-drift", "current local reference digest changed")
    return load_json_object(raw, label="stage binding reference"), raw


def neutral_stage_binding(root: Path, registry_raw: bytes, entry: dict[str, Any], stage: str) -> dict[str, Any]:
    """Recompute the closed identity from bounded current reference bytes."""
    host, _ = read_binding_reference(root, entry["hostModelProfile"])
    validated = validate_stage_binding(entry, host_profile=host)
    launch, _ = read_binding_reference(root, entry["launchProfile"])
    parameter, _ = read_binding_reference(root, entry["parameterSupport"]["evidence"])
    receipt, _ = read_binding_reference(root, entry["qualificationEvidence"])
    if validate_local_launch_profile(launch)["status"] != "PASS" or launch.get("adapterId") != entry["adapterId"]:
        raise LifecycleError("stage-binding-launch-mismatch", "current local launch profile is invalid or mismatched")
    if not isinstance(parameter.get("source"), str) or not parameter["source"].startswith("https://"):
        raise LifecycleError("stage-binding-parameter-evidence", "current parameter evidence is missing its source")
    _validate_version_reference(entry, launch, receipt)
    model_class = validated["modelClass"]
    return {
        "stage": stage,
        "modelClass": model_class,
        "selectedBindingDigest": validated["bindingDigest"],
        "registrySha256": hashlib.sha256(registry_raw).hexdigest(),
        "hostModelProfileSha256": entry["hostModelProfile"]["sha256"],
        "hostBindingDigest": canonical_digest(host["bindings"][model_class]),
        "launchProfileSha256": entry["launchProfile"]["sha256"],
        "parameterSupportSha256": entry["parameterSupport"]["evidence"]["sha256"],
        "versionQualificationSha256": entry["qualificationEvidence"]["sha256"],
        "parameterDigest": canonical_digest(entry["hostParameters"]),
    }


def _validate_version_reference(entry: dict[str, Any], launch: dict[str, Any], receipt: dict[str, Any]) -> None:
    policy = launch.get("qualification", {})
    if not policy or entry["qualificationEvidence"]["path"] != ".alk/host-launch/" + str(policy.get("receiptFile", "")):
        raise LifecycleError(
            "stage-binding-qualification-path", "canonical version evidence must match the exact profile policy path"
        )
    expected = {
        "schemaVersion": QUALIFICATION_RECEIPT_SCHEMA,
        "status": "PASS",
        "adapterId": entry["adapterId"],
        "profileDigest": canonical_digest(launch),
        "expectedHostVersion": policy.get("expectedVersion"),
        "actualHostVersion": policy.get("expectedVersion"),
        "processCalls": 1,
        "modelCallsStarted": False,
        "productionPromotionClaimed": False,
        "blockers": [],
    }
    if any(receipt.get(key) != value for key, value in expected.items()) or receipt.get(
        "receiptDigest"
    ) != canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"}):
        raise LifecycleError(
            "stage-binding-qualification-invalid", "current canonical version receipt does not bind this profile"
        )


def recompute_stage_binding(
    *,
    root: Path | None,
    profile_path: str | None,
    proposed: dict[str, Any] | None,
    profile_digest: str | None,
    host_profile: dict[str, Any] | None,
    adapter_id: str,
    route: dict[str, Any],
) -> dict[str, Any] | None:
    """The submitted digest selects only an entry approved by current trusted inputs."""
    if root is None or profile_path is None:
        if proposed is not None:
            raise LifecycleError(
                "stage-binding-trusted-input-required", "stage adoption requires the trusted current project context"
            )
        return None
    path = root / normalize_repo_path(profile_path, label="project profile")
    if not path.exists():
        if proposed is not None:
            raise LifecycleError("stage-binding-trusted-input-required", "trusted current project profile is missing")
        return None
    profile = load_json_object(read_authority_bytes(path, root=root, max_bytes=65536), label="project profile")
    registry_path = profile.get("policies", {}).get("executionBindings")
    if not registry_path:
        if proposed is not None:
            raise LifecycleError("stage-binding-opt-in-required", "stage selector cannot add an absent project opt-in")
        return None
    proposed = validate_neutral_stage_binding(proposed)
    if canonical_digest(profile) != profile_digest:
        raise LifecycleError("stage-binding-profile-drift", "trusted project profile digest changed")
    local_reference({"path": registry_path, "sha256": "0" * 64})
    raw = read_authority_bytes(root / registry_path, root=root, max_bytes=MAX_REGISTRY_BYTES)
    registry = load_json_object(raw, label="stage binding registry")
    validate_stage_registry(registry)
    approved = ordered_stage_refs(profile, proposed["stage"])
    entries = [registry["bindings"].get(ref) for ref in approved]
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and canonical_digest(entry) == proposed["selectedBindingDigest"]
    ]
    if len(matches) != 1:
        raise LifecycleError(
            "stage-binding-not-approved", "selected digest must identify one current approved stage member"
        )
    entry = matches[0]
    actual = neutral_stage_binding(root, raw, entry, proposed["stage"])
    current_host, _ = read_binding_reference(root, entry["hostModelProfile"])
    if (
        entry["adapterId"] != adapter_id
        or current_host != host_profile
        or actual["modelClass"] != route.get("modelClass")
        or actual["hostBindingDigest"] != route.get("hostBindingDigest")
    ):
        raise LifecycleError(
            "stage-binding-floor-refused", "current selected binding differs from the existing frozen model route"
        )
    if actual != proposed:
        raise LifecycleError(
            "stage-binding-identity-drift", "submitted stage identity differs from current trusted inputs"
        )
    return actual


def availability_probe_only(manifest: dict[str, Any], task_id: str) -> bool:
    """Read neutral purpose from the actual frozen task; never infer caller intent."""
    tasks = [row for row in manifest.get("workstreams", []) if isinstance(row, dict) and row.get("id") == task_id]
    if len(tasks) != 1:
        raise LifecycleError("stage-binding-purpose-invalid", "task purpose requires one frozen workstream")
    policy = tasks[0].get("executionPolicy", {})
    value = policy.get("availabilityProbeOnly", False) if isinstance(policy, dict) else None
    if type(value) is not bool:
        raise LifecycleError("stage-binding-purpose-invalid", "availabilityProbeOnly must be a frozen boolean")
    return value
