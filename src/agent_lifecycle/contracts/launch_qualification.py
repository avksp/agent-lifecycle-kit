"""Pure validation for version-bound local launch qualification policy."""

from __future__ import annotations

import re
from typing import Any

QUALIFICATION_POLICY_SCHEMA = "agent-host-launch-qualification-policy.v1"
QUALIFICATION_RECEIPT_SCHEMA = "agent-host-launch-qualification-receipt.v1"
QUALIFIED_PROFILE_STATUS = "VERSION_BOUND_LOCAL"
_VERSION = re.compile(r"(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9])")
_SAFE_RECEIPT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.json$")


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
    "validate_qualification_policy",
    "version_pattern",
]
