"""Pure validation for version-bound local launch qualification policy."""

from __future__ import annotations

import re
from typing import Any

QUALIFICATION_POLICY_SCHEMA = "agent-host-launch-qualification-policy.v1"
QUALIFICATION_RECEIPT_SCHEMA = "agent-host-launch-qualification-receipt.v1"
QUALIFIED_PROFILE_STATUS = "VERSION_BOUND_LOCAL"
_VERSION = re.compile(r"(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9])")
_SAFE_RECEIPT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.json$")
_STABLE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", re.ASCII)
_REPORTED = re.compile(r"(?<![\w.+-])([0-9]+\.[0-9]+\.[0-9]+(?:[-+][\w.+-]+)?)(?![\w.+-])", re.ASCII)


def stable_version(value: str) -> tuple[int, int, int]:
    """Parse a stable numeric version; suffixes and leading zeroes need a policy."""
    match = _STABLE.fullmatch(value) if isinstance(value, str) and len(value) <= 128 else None
    if match is None:
        raise ValueError("invalid stable version")
    return int(match[1]), int(match[2]), int(match[3])


def observed_version(text: str) -> str | None:
    """Accept exactly one stable version from bounded discovery output."""
    if len(text) > 4096:
        return None
    matches = list(_REPORTED.finditer(text))
    if len(matches) != 1:
        return None
    value = matches[0][1]
    try:
        stable_version(value)
    except ValueError:
        return None
    return value


def version_policy_bounds(policy: dict[str, Any]) -> tuple[str, str] | None:
    """Validate reported, exact, or inclusive same-major ``minimum..maximum``."""
    mode, accepted = policy.get("mode"), policy.get("accepted")
    if mode == "reported" and accepted == "any-version":
        return None
    if not isinstance(accepted, str):
        raise ValueError("invalid version policy")
    parts = accepted.split("..") if mode == "range" else [accepted, accepted]
    if mode not in {"exact", "range"} or len(parts) != 2:
        raise ValueError("invalid version policy")
    minimum, maximum = parts
    low, high = stable_version(minimum), stable_version(maximum)
    if low > high or low[0] != high[0]:
        raise ValueError("invalid version range")
    return minimum, maximum


def version_policy_accepts(policy: dict[str, Any], text: str) -> bool:
    """Apply a declared policy; observation-only behavior remains unchanged."""
    try:
        bounds = version_policy_bounds(policy)
        if bounds is None:
            return True
        actual = observed_version(text)
        return actual is not None and stable_version(bounds[0]) <= stable_version(actual) <= stable_version(bounds[1])
    except ValueError:
        return False


def validate_qualification_policy(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the policy fields that make a local qualification receipt useful."""

    policy = profile.get("qualification")
    if policy is None:
        return []
    blockers: list[dict[str, Any]] = []
    if not isinstance(policy, dict) or policy.get("schemaVersion") != QUALIFICATION_POLICY_SCHEMA:
        return [{"code": "qualified-launch-policy-schema"}]
    expected = policy.get("expectedVersion")
    if not isinstance(expected, str) or _VERSION.fullmatch(expected) is None:
        blockers.append({"code": "qualified-launch-expected-version"})
    receipt_file = policy.get("receiptFile")
    if not isinstance(receipt_file, str) or not _SAFE_RECEIPT_NAME.fullmatch(receipt_file):
        blockers.append({"code": "qualified-launch-receipt-file"})
    if policy.get("requiredForManagedTask") is not True:
        blockers.append({"code": "qualified-launch-managed-task-policy"})
    if policy.get("modelCallsForPreflight") != 0 or policy.get("maxPreflightProcesses") != 1:
        blockers.append({"code": "qualified-launch-preflight-budget"})
    return blockers


def version_pattern() -> re.Pattern[str]:
    return _VERSION


__all__ = [
    "QUALIFICATION_POLICY_SCHEMA",
    "QUALIFICATION_RECEIPT_SCHEMA",
    "QUALIFIED_PROFILE_STATUS",
    "observed_version",
    "stable_version",
    "validate_qualification_policy",
    "version_pattern",
    "version_policy_accepts",
    "version_policy_bounds",
]
