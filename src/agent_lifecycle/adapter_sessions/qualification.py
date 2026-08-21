"""Version-bound qualification for shipped local host launch profiles."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.launch_qualification import (
    QUALIFICATION_POLICY_SCHEMA,
    QUALIFICATION_RECEIPT_SCHEMA,
    QUALIFIED_PROFILE_STATUS,
    validate_qualification_policy,
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
    path = adapter_root / "launch_profile.py"
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
    combined = "\n".join(
        str(probe_receipt.get(stream, {}).get("tail", ""))
        for stream in ("stdout", "stderr")
    )
    match = _VERSION.search(combined)
    actual = match.group(1) if match else None
    expected = policy.get("expectedVersion")
    blockers: list[dict[str, Any]] = []
    if probe_receipt.get("status") != "PASS":
        blockers.append({"code": "qualified-launch-probe-failed"})
    if actual is None:
        blockers.append({"code": "qualified-launch-version-missing"})
    elif actual != expected:
        blockers.append({"code": "qualified-launch-version-mismatch", "expectedVersion": expected, "actualVersion": actual})
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
        raise LifecycleError("qualified-launch-policy-invalid", "qualification policy is invalid", {"blockers": blockers})
    path = project_root.resolve() / ".alk" / "host-launch" / policy["receiptFile"]
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to((project_root.resolve() / ".alk" / "host-launch").resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise LifecycleError("qualified-launch-receipt-missing", "run host-launch preflight before managed launch") from exc
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
    if any(receipt.get(key) != value for key, value in expected.items()) or receipt.get("receiptDigest") != canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"}):
        raise LifecycleError("qualified-launch-receipt-invalid", "qualification receipt does not bind this profile and version")
    if executable_identity is not None and receipt.get("executableIdentity") != executable_identity:
        raise LifecycleError("qualified-launch-executable-identity-mismatch", "qualification receipt does not bind the current executable identity")
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
            {"preparationCommand": f"agent-lifecycle adapter launch-profile --adapter {profile.get('adapterId')} --out .alk/host-launch/{profile.get('adapterId')}.json"},
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
