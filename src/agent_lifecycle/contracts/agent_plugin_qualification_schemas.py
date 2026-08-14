"""Contracts for local Agent Plugins client qualification."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schema_builders import open_object_schema


PROFILE_SCHEMA = "agent-plugin-qualification-profile.v1"
RECEIPT_SCHEMA = "agent-plugin-qualification-receipt.v1"
VALIDATION_SCHEMA = "agent-plugin-qualification-validation.v1"

QUALIFICATION_STATUSES = ("OFFLINE_VALIDATED", "QUALIFIED", "BLOCKED", "UNAVAILABLE")
PROFILE_STATUSES = ("SUPPORTED", "UNAVAILABLE")
CANONICAL_SKILLS = (
    "agent-first-planning",
    "agent-plan-to-workers",
    "agent-workflow-orchestrator",
    "audit-agent-plan",
    "audit-plan-implementation",
    "bug-forensics",
    "issue-to-spec",
)

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}

AGENT_PLUGIN_QUALIFICATION_SCHEMAS: dict[str, dict[str, Any]] = {
    PROFILE_SCHEMA: open_object_schema(
        PROFILE_SCHEMA,
        required=[
            "schemaVersion",
            "profileId",
            "adapterId",
            "client",
            "host",
            "package",
            "discovery",
            "installation",
            "environment",
            "hostVersionPolicy",
            "qualification",
            "descriptorBoundary",
            "profileDigest",
        ],
        properties={
            "profileId": {"type": "string", "minLength": 1},
            "adapterId": {"type": "string", "minLength": 1},
            "client": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "package": {"type": "object"},
            "discovery": {"type": "object"},
            "installation": {"type": "object"},
            "environment": {"type": "object"},
            "hostVersionPolicy": {"type": "object"},
            "qualification": {"type": "object"},
            "descriptorBoundary": {"type": "object"},
            "profileDigest": _DIGEST,
        },
    ),
    RECEIPT_SCHEMA: open_object_schema(
        RECEIPT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "profileId",
            "profileDigest",
            "packageVersion",
            "packageDigest",
            "packageSkillCount",
            "requiredSkillCount",
            "clientVersion",
            "checks",
            "processCalls",
            "modelCallsStarted",
            "networkCallsStarted",
            "installationStarted",
            "nativeConfigWritten",
            "lifecycleCoverageClaimed",
            "managedLaunchProofClaimed",
            "rawOutputStored",
            "secretsStored",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": list(QUALIFICATION_STATUSES)},
            "adapterId": {"type": "string", "minLength": 1},
            "profileId": {"type": "string", "minLength": 1},
            "profileDigest": _DIGEST,
            "packageVersion": {"type": ["string", "null"]},
            "packageDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "packageSkillCount": {"type": "integer", "minimum": 0},
            "requiredSkillCount": {"type": "integer", "minimum": 0},
            "clientVersion": {"type": ["string", "null"]},
            "checks": {"type": "array", "items": {"type": "object"}},
            "processCalls": {"type": "integer", "minimum": 0, "maximum": 2},
            "modelCallsStarted": {"const": False},
            "networkCallsStarted": {"const": False},
            "installationStarted": {"const": False},
            "nativeConfigWritten": {"const": False},
            "lifecycleCoverageClaimed": {"const": False},
            "managedLaunchProofClaimed": {"const": False},
            "rawOutputStored": {"const": False},
            "secretsStored": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    VALIDATION_SCHEMA: open_object_schema(
        VALIDATION_SCHEMA,
        required=["schemaVersion", "status", "checks", "blockers", "productionPromotionClaimed", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}


def validate_qualification_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate a data-only client profile and its self-digest."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        return _validation([_issue("profile-not-object")])
    _required_text(profile, "schemaVersion", PROFILE_SCHEMA, blockers)
    for field in ("profileId", "adapterId", "client", "host"):
        if not isinstance(profile.get(field), str) or not profile[field].strip():
            blockers.append(_issue("profile-field-invalid", field=field))

    package = profile.get("package")
    if not isinstance(package, dict):
        blockers.append(_issue("profile-package-invalid"))
    else:
        if package.get("name") != "agent-lifecycle-kit":
            blockers.append(_issue("profile-package-name", actual=package.get("name")))
        if package.get("manifestPath") != "plugin.json" or package.get("skillsPath") != "skills":
            blockers.append(_issue("profile-package-paths"))
        skills = package.get("requiredSkills")
        if skills != list(CANONICAL_SKILLS):
            blockers.append(_issue("profile-required-skills", expected=list(CANONICAL_SKILLS), actual=skills))

    discovery = profile.get("discovery")
    if not isinstance(discovery, dict):
        blockers.append(_issue("profile-discovery-invalid"))
    else:
        for field in ("versionArgs", "helpArgs"):
            value = discovery.get(field)
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
                blockers.append(_issue("profile-discovery-args", field=field))
        for field in ("pluginManifestPath", "skillsPath"):
            value = discovery.get(field)
            if not isinstance(value, str) or not value or value.startswith(("/", "~")) or ".." in value.split("/"):
                blockers.append(_issue("profile-discovery-path", field=field))
        markers = discovery.get("requiredMarkers", [])
        if not isinstance(markers, list) or not all(isinstance(item, str) and item for item in markers):
            blockers.append(_issue("profile-discovery-markers"))

    installation = profile.get("installation")
    if not isinstance(installation, dict):
        blockers.append(_issue("profile-installation-invalid"))
    else:
        if installation.get("owner") != "client" or installation.get("automatic") is not False or installation.get("writesAllowed") is not False:
            blockers.append(_issue("profile-installation-boundary"))

    environment = profile.get("environment")
    if not isinstance(environment, dict):
        blockers.append(_issue("profile-environment-invalid"))
    else:
        for field in ("allow", "allowPatterns"):
            value = environment.get(field, [])
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                blockers.append(_issue("profile-environment-allowlist", field=field))
        if environment.get("allowPatterns"):
            blockers.append(_issue("profile-environment-wildcard"))

    host_version_policy = profile.get("hostVersionPolicy")
    if not isinstance(host_version_policy, dict):
        blockers.append(_issue("profile-host-version-policy-invalid"))
    else:
        mode = host_version_policy.get("mode")
        accepted = host_version_policy.get("accepted")
        if mode not in {"reported", "exact", "range"} or not isinstance(accepted, str) or not accepted.strip():
            blockers.append(_issue("profile-host-version-policy-invalid", mode=mode))
        elif mode == "reported" and accepted != "any-version":
            blockers.append(_issue("profile-host-version-policy-reported-invalid", accepted=accepted))
        elif mode in {"exact", "range"}:
            blockers.append(_issue("profile-host-version-policy-unsupported", mode=mode))

    qualification = profile.get("qualification")
    if not isinstance(qualification, dict):
        blockers.append(_issue("profile-qualification-invalid"))
    else:
        if qualification.get("status") not in PROFILE_STATUSES:
            blockers.append(_issue("profile-qualification-status", actual=qualification.get("status")))
        if qualification.get("mode") != "explicit-read-only":
            blockers.append(_issue("profile-qualification-mode"))
        if qualification.get("maxProcesses") != 2 or qualification.get("timeoutSeconds") != 10 or qualification.get("maxOutputBytes") != 262144:
            blockers.append(_issue("profile-qualification-limits"))
        if qualification.get("modelCalls") != 0 or qualification.get("hostLaunch") is not True:
            blockers.append(_issue("profile-qualification-safety"))

    boundary = profile.get("descriptorBoundary")
    if not isinstance(boundary, dict) or boundary.get("maturityReadOnly") is not True or boundary.get("managedLaunchReadOnly") is not True:
        blockers.append(_issue("profile-descriptor-boundary"))
    if "managedLaunch" in profile or "maturity" in profile:
        blockers.append(_issue("profile-descriptor-override"))

    digest = profile.get("profileDigest")
    expected_digest = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
    if digest != expected_digest:
        blockers.append(_issue("profile-digest-mismatch", expected=expected_digest, actual=digest))
    return _validation(blockers, checked_digest=digest if isinstance(digest, str) else None)


def build_qualification_receipt(
    *,
    profile: dict[str, Any],
    status: str,
    package_version: str | None,
    package_digest: str | None,
    package_skill_count: int,
    checks: list[dict[str, Any]],
    process_calls: int = 0,
    client_version: str | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if status not in QUALIFICATION_STATUSES:
        raise LifecycleError("plugin-qualification-status-invalid", "unsupported plugin qualification status")
    profile_validation = validate_qualification_profile(profile)
    if profile_validation["status"] != "PASS":
        raise LifecycleError("plugin-qualification-profile-invalid", "qualification profile failed validation", profile_validation)
    if process_calls < 0 or process_calls > 2:
        raise LifecycleError("plugin-qualification-process-count-invalid", "process call count is outside the profile limit")
    body = {
        "schemaVersion": RECEIPT_SCHEMA,
        "status": status,
        "adapterId": profile["adapterId"],
        "profileId": profile["profileId"],
        "profileDigest": profile["profileDigest"],
        "packageVersion": package_version,
        "packageDigest": package_digest,
        "packageSkillCount": package_skill_count,
        "requiredSkillCount": len(CANONICAL_SKILLS),
        "clientVersion": client_version,
        "checks": deepcopy(checks),
        "processCalls": process_calls,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "installationStarted": False,
        "nativeConfigWritten": False,
        "lifecycleCoverageClaimed": False,
        "managedLaunchProofClaimed": False,
        "rawOutputStored": False,
        "secretsStored": False,
        "blockers": deepcopy(blockers or []),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_qualification_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        return _validation([_issue("receipt-not-object")])
    if receipt.get("schemaVersion") != RECEIPT_SCHEMA:
        blockers.append(_issue("receipt-schema-mismatch", actual=receipt.get("schemaVersion")))
    if receipt.get("status") not in QUALIFICATION_STATUSES:
        blockers.append(_issue("receipt-status-invalid", actual=receipt.get("status")))
    for field in ("profileDigest", "receiptDigest"):
        value = receipt.get(field)
        if not isinstance(value, str) or len(value) != 64:
            blockers.append(_issue("receipt-digest-invalid", field=field))
    for field in (
        "modelCallsStarted",
        "networkCallsStarted",
        "installationStarted",
        "nativeConfigWritten",
        "lifecycleCoverageClaimed",
        "managedLaunchProofClaimed",
        "rawOutputStored",
        "secretsStored",
        "productionPromotionClaimed",
    ):
        if receipt.get(field) is not False:
            blockers.append(_issue("receipt-safety-flag", field=field))
    process_calls = receipt.get("processCalls")
    if not isinstance(process_calls, int) or process_calls < 0 or process_calls > 2:
        blockers.append(_issue("receipt-process-count"))
    if receipt.get("status") == "OFFLINE_VALIDATED" and process_calls != 0:
        blockers.append(_issue("receipt-offline-process-call"))
    if receipt.get("status") == "QUALIFIED" and process_calls < 1:
        blockers.append(_issue("receipt-qualified-without-probe"))
    expected = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected:
        blockers.append(_issue("receipt-digest-mismatch", expected=expected, actual=receipt.get("receiptDigest")))
    return _validation(blockers, checked_digest=receipt.get("receiptDigest") if isinstance(receipt.get("receiptDigest"), str) else None)


def _required_text(payload: dict[str, Any], field: str, expected: str, blockers: list[dict[str, Any]]) -> None:
    if payload.get(field) != expected:
        blockers.append(_issue("schema-version-mismatch", field=field, expected=expected, actual=payload.get(field)))


def _issue(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _validation(blockers: list[dict[str, Any]], *, checked_digest: str | None = None) -> dict[str, Any]:
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "checks": [{"name": "qualification-contract", "status": "PASS" if not blockers else "FAIL"}],
        "blockers": blockers,
        "checkedDigest": checked_digest,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_qualification_receipt_pass(receipt: dict[str, Any]) -> dict[str, Any]:
    validation = validate_qualification_receipt(receipt)
    if validation["status"] != "PASS":
        raise LifecycleError("plugin-qualification-receipt-invalid", "qualification receipt failed validation", validation)
    return receipt
