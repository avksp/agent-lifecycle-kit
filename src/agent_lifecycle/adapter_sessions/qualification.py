"""Version-bound qualification for shipped local host launch profiles."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.launch_qualification import (
    QUALIFICATION_RECEIPT_SCHEMA,
    validate_qualification_policy,
)
from agent_lifecycle.contracts.structured_result_schemas import (
    STRUCTURED_RESULT_SELECTION_SCHEMA,
    build_structured_result_capability,
    select_structured_result_mode,
    validate_structured_result_selection,
)
from agent_lifecycle.contracts.validation import load_bounded_literal_profile

_VERSION = re.compile(r"(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9])")
_SAFE_RECEIPT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.json$")


def qualified_profile_output_path(value: str) -> Path:
    """Constrain generated profiles to one ignored project-local directory."""

    path = Path(value)
    if path.is_absolute() or len(path.parts) != 3 or path.parts[:2] != (".alk", "host-launch"):
        raise LifecycleError("qualified-launch-output-path", "profile output must be .alk/host-launch/<name>.json")
    if not _SAFE_RECEIPT_NAME.fullmatch(path.name):
        raise LifecycleError("qualified-launch-output-path", "profile output filename is invalid")
    root = Path.cwd().absolute()
    current = root
    for part in path.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise LifecycleError("qualified-launch-output-path", "profile output path must not contain symlinks")
    return path


def load_shipped_launch_profile(adapter_id: str, *, repository_root: Path | None = None) -> dict[str, Any]:
    """Load one literal-only adapter profile without importing adapter code."""

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", adapter_id):
        raise LifecycleError("qualified-launch-adapter-invalid", "adapter id is invalid")
    root = (repository_root or Path.cwd()).resolve()
    adapter_root = root / "adapters" / adapter_id
    profile = load_bounded_literal_profile(
        Path("launch_profile.py"),
        root=adapter_root,
        error_prefix="qualified-launch-profile",
    )
    if profile.get("adapterId") != adapter_id:
        raise LifecycleError("qualified-launch-profile-adapter-mismatch", "shipped profile adapter does not match")
    return profile


def shipped_profile_digest(adapter_id: str, *, repository_root: Path | None = None) -> str | None:
    """Return the digest of the shipped literal profile when this checkout has one."""

    try:
        return canonical_digest(load_shipped_launch_profile(adapter_id, repository_root=repository_root))
    except LifecycleError:
        return None


def build_qualification_receipt(
    *,
    profile: dict[str, Any],
    profile_digest: str,
    probe_receipt: dict[str, Any],
    executable_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a successful version probe to one exact local profile."""

    policy = profile.get("qualification")
    if not isinstance(policy, dict):
        raise LifecycleError("qualified-launch-policy-missing", "profile does not require qualification")
    combined = "\n".join(str(probe_receipt.get(stream, {}).get("tail", "")) for stream in ("stdout", "stderr"))
    match = _VERSION.search(combined)
    actual = match.group(1) if match else None
    expected = policy.get("expectedVersion")
    blockers: list[dict[str, Any]] = []
    if probe_receipt.get("status") != "PASS":
        blockers.append({"code": "qualified-launch-probe-failed"})
    if actual is None:
        blockers.append({"code": "qualified-launch-version-missing"})
    elif actual != expected:
        blockers.append(
            {"code": "qualified-launch-version-mismatch", "expectedVersion": expected, "actualVersion": actual}
        )
    body = {
        "schemaVersion": QUALIFICATION_RECEIPT_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "adapterId": profile.get("adapterId"),
        "expectedHostVersion": expected,
        "actualHostVersion": actual,
        "profileDigest": profile_digest,
        "executableIdentity": executable_identity,
        "probeReceiptDigest": probe_receipt.get("receiptDigest"),
        "processCalls": 1,
        "modelCallsStarted": False,
        "planningSupportStatus": planning_support_status(profile),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def write_qualification_receipt(project_root: Path, profile: dict[str, Any], receipt: dict[str, Any]) -> Path:
    policy = profile["qualification"]
    path = project_root.resolve() / ".alk" / "host-launch" / policy["receiptFile"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LifecycleError("qualified-launch-receipt-path", "qualification receipt must not be a symlink")
    if path.exists():
        existing = read_json_object(path, label="host launch qualification receipt")
        if existing != receipt:
            raise LifecycleError(
                "qualified-launch-receipt-already-exists",
                "qualification receipts are immutable; use a fresh profile path after a version change",
            )
        return path
    write_json_create(path, receipt)
    return path


def require_qualification_receipt(
    *,
    project_root: Path,
    profile: dict[str, Any],
    profile_digest: str,
    executable_identity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the bound receipt or fail before the process boundary."""

    policy = profile.get("qualification")
    if policy is None:
        return None
    blockers = validate_qualification_policy(profile)
    if blockers:
        raise LifecycleError(
            "qualified-launch-policy-invalid", "qualification policy is invalid", {"blockers": blockers}
        )
    path = project_root.resolve() / ".alk" / "host-launch" / policy["receiptFile"]
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to((project_root.resolve() / ".alk" / "host-launch").resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise LifecycleError(
            "qualified-launch-receipt-missing", "run host-launch preflight before managed launch"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise LifecycleError("qualified-launch-receipt-path", "qualification receipt must be a regular file")
    receipt = read_json_object(path, label="host launch qualification receipt")
    expected = {
        "schemaVersion": QUALIFICATION_RECEIPT_SCHEMA,
        "status": "PASS",
        "adapterId": profile.get("adapterId"),
        "expectedHostVersion": policy.get("expectedVersion"),
        "actualHostVersion": policy.get("expectedVersion"),
        "profileDigest": profile_digest,
        "processCalls": 1,
        "modelCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    if any(receipt.get(key) != value for key, value in expected.items()) or receipt.get(
        "receiptDigest"
    ) != canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"}):
        raise LifecycleError(
            "qualified-launch-receipt-invalid", "qualification receipt does not bind this profile and version"
        )
    if executable_identity is not None and receipt.get("executableIdentity") != executable_identity:
        raise LifecycleError(
            "qualified-launch-executable-identity-mismatch",
            "qualification receipt does not bind the current executable identity",
        )
    if receipt.get("blockers") != []:
        raise LifecycleError("qualified-launch-receipt-invalid", "qualification receipt contains blockers")
    return receipt


def planning_support_status(profile: dict[str, Any]) -> str:
    planning = profile.get("planningOnly")
    if not isinstance(planning, dict):
        return "PLANNING_ONLY_UNSUPPORTED"
    value = planning.get("planningSupportStatus")
    if value in {"PLANNING_ONLY_QUALIFIED", "PLANNING_ONLY_UNSUPPORTED"}:
        return str(value)
    return "PLANNING_ONLY_UNSUPPORTED"


def require_planning_qualification_receipt(
    *,
    project_root: Path,
    profile: dict[str, Any],
    profile_digest: str,
    executable_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require both release planning evidence and a bound local version probe."""

    planning = profile.get("planningOnly")
    if not isinstance(planning, dict) or planning.get("status") != "CANDIDATE":
        raise LifecycleError(
            "planning-launch-profile-unsupported",
            "adapter does not declare a planning-only profile",
        )
    if planning_support_status(profile) != "PLANNING_ONLY_QUALIFIED":
        raise LifecycleError(
            "planning-launch-qualification-required",
            "planning launch is unsupported until exact-version live qualification passes",
            {
                "preparationCommand": (
                    "agent-lifecycle adapter launch-profile "
                    f"--adapter {profile.get('adapterId')} "
                    f"--out .alk/host-launch/{profile.get('adapterId')}.json"
                )
            },
        )
    receipt = require_qualification_receipt(
        project_root=project_root,
        profile=profile,
        profile_digest=profile_digest,
        executable_identity=executable_identity,
    )
    if not isinstance(receipt, dict) or receipt.get("planningSupportStatus") != "PLANNING_ONLY_QUALIFIED":
        raise LifecycleError(
            "planning-launch-qualification-receipt-invalid",
            "local version receipt is not bound to qualified planning support",
        )
    return receipt


def build_structured_result_qualification_receipt(
    *,
    operation_id: str,
    adapter_id: str,
    descriptor_digest: str,
    host_version: str,
    model_class: str,
    required_mode: str,
    required_schema_digest: str,
    capability_manifest_digest: str,
    capability_level: str,
    evidence_digest: str,
    measured_run_count: int,
    plan_digest: str,
    lock_digest: str,
) -> dict[str, Any]:
    """Build an advisory, operation-bound structured-result qualification receipt."""

    capability = build_structured_result_capability(
        operation_id=operation_id,
        adapter_id=adapter_id,
        descriptor_digest=descriptor_digest,
        host_version=host_version,
        model_class=model_class,
        capability_level=capability_level,
        qualification_status="QUALIFIED" if capability_level != "UNAVAILABLE" else "UNAVAILABLE",
        capability_manifest_digest=capability_manifest_digest,
        evidence_digest=evidence_digest,
        measured_run_count=measured_run_count,
    )
    selection = select_structured_result_mode(
        [capability],
        operation_id=operation_id,
        required_mode=required_mode,
        adapter_id=adapter_id,
        descriptor_digest=descriptor_digest,
        host_version=host_version,
        model_class=model_class,
        capability_manifest_digest=capability_manifest_digest,
        required_schema_digest=required_schema_digest,
        lineage={"planDigest": plan_digest, "lockDigest": lock_digest},
    )
    body = {
        "schemaVersion": "agent-structured-result-qualification-receipt.v1",
        "status": "PASS" if selection["status"] == "PASS" else "UNAVAILABLE",
        "qualificationStatus": "QUALIFIED" if selection["status"] == "PASS" else "UNAVAILABLE",
        "operationId": operation_id,
        "adapterId": adapter_id,
        "descriptorDigest": descriptor_digest,
        "hostVersion": host_version,
        "modelClass": model_class,
        "capabilityManifestDigest": capability_manifest_digest,
        "requiredMode": required_mode,
        "requiredSchemaDigest": required_schema_digest,
        "planDigest": plan_digest,
        "lockDigest": lock_digest,
        "capability": capability,
        "selection": selection,
        "advisoryOnly": True,
        "automaticRouteAdoptionEligible": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_structured_result_qualification_receipt(
    receipt: dict[str, Any], *, expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate structured-result qualification without granting workflow authority."""

    blockers: list[dict[str, Any]] = []
    if receipt.get("schemaVersion") != "agent-structured-result-qualification-receipt.v1":
        blockers.append({"code": "structured-result-qualification-schema"})
    if receipt.get("advisoryOnly") is not True or receipt.get("automaticRouteAdoptionEligible") is not False:
        blockers.append({"code": "structured-result-qualification-authority"})
    if receipt.get("modelCallsStarted") is not False or receipt.get("hostLaunchStarted") is not False:
        blockers.append({"code": "structured-result-qualification-side-effect"})
    for key, value in (expected or {}).items():
        if receipt.get(key) != value:
            blockers.append({"code": "structured-result-qualification-lineage", "field": key})
    selection = receipt.get("selection")
    if not isinstance(selection, dict):
        blockers.append({"code": "structured-result-qualification-selection"})
    else:
        selection_validation = validate_structured_result_selection(
            selection,
            expected={
                key: receipt.get(key)
                for key in (
                    "operationId",
                    "adapterId",
                    "descriptorDigest",
                    "hostVersion",
                    "modelClass",
                    "capabilityManifestDigest",
                    "requiredSchemaDigest",
                )
                if receipt.get(key) is not None
            },
        )
        if selection_validation["status"] != "PASS":
            blockers.append({"code": "structured-result-qualification-selection-invalid"})
        if receipt.get("status") == "PASS" and selection.get("schemaVersion") != STRUCTURED_RESULT_SELECTION_SCHEMA:
            blockers.append({"code": "structured-result-qualification-selection-schema"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "structured-result-qualification-digest"})
    body = {
        "schemaVersion": "agent-structured-result-qualification-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "qualificationStatus": receipt.get("qualificationStatus"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}
