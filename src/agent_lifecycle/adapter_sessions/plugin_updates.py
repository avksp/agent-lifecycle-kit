"""Host-neutral advice and explicit refusal; no native update dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from agent_lifecycle.contracts import canonical_digest, sha256_hex
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.plugin_update_schemas import UPDATE_SOURCE
from agent_lifecycle.contracts.plugin_update_validation import (
    MAX_PLAN_INPUT_BYTES,
    MAX_UPDATE_BYTES,
    require_update,
    update_digest,
    update_object,
    update_report,
    update_version,
    validate_update_report,
    validate_update_request,
)
from agent_lifecycle.diagnostics.plugin_updates import observe_update_identities


def _assessment_subjects(assessment: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    plans = assessment["details"].get("plans")
    require_update(isinstance(plans, list) and 0 < len(plans) <= 32, "offer needs1..32 assessed plans")
    plans = cast(list[dict[str, Any]], plans)
    subjects: dict[str, str] = {}
    for plan in plans:
        require_update(
            isinstance(plan, dict) and plan.get("structuralResult") == "PASS",
            "offer requires structurally verified plans",
        )
        hashes = plan.get("inputSHA256")
        require_update(isinstance(hashes, dict) and 0 < len(hashes) <= 64, "offer input file cap64")
        hashes = cast(dict[str, str], hashes)
        require_update(
            isinstance(plan.get("manifest"), str) and plan["manifest"] in hashes,
            "assessed manifest must have an exact input hash",
        )
        require_update(isinstance(plan.get("lifecycle"), dict), "assessed lifecycle unavailable")
        for path, digest in hashes.items():
            normalized = normalize_repo_path(path)
            update_digest(digest)
            require_update(
                normalized not in subjects or subjects[normalized] == digest, "conflicting assessed file identity"
            )
            subjects[normalized] = digest
    return subjects, plans


def _recheck_subjects(root: Path, subjects: dict[str, str]) -> None:
    remaining = MAX_PLAN_INPUT_BYTES
    for path, digest in subjects.items():
        require_update(remaining > 0, "offer aggregate input cap8MiB")
        body = read_stable_repository_file(root, path, max_bytes=min(MAX_UPDATE_BYTES, remaining))
        remaining -= len(body)
        require_update(sha256_hex(body) == digest, "assessment became stale; reassess changed input")


def _target(request: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    target = update_object(
        assessment["details"].get("target"), {"version", "sourceCommit"}, {"version", "sourceCommit"}
    )
    version = update_version(target.get("version"))
    commit = target["sourceCommit"]
    if commit is not None:
        update_digest(commit, 40)
    require_update(request.get("targetVersion", version) == version, "offer target differs from request")
    require_update(request.get("pin") in (None, "v" + version), "offer differs from immutable pin")
    require_update(
        commit is None or request.get("trustedTargetCommit", commit) == commit, "offer commit differs from request"
    )
    require_update(
        request.get("channel", "stable") == "prerelease" or "-" not in version, "offer prerelease is not opted in"
    )
    return {"version": version, "sourceCommit": commit, "source": UPDATE_SOURCE}


def _manual_codex_commands(version: str) -> list[list[str]]:
    # Inert native CLI shapes, not a transaction, qualification or permission.
    return [
        ["codex", "plugin", "marketplace", "remove", "agent-lifecycle-kit"],
        ["codex", "plugin", "marketplace", "add", UPDATE_SOURCE + ".git", "--ref", "v" + version, "--json"],
        ["codex", "plugin", "add", "agent-lifecycle-kit@agent-lifecycle-kit", "--json"],
        ["codex", "plugin", "list", "--marketplace", "agent-lifecycle-kit", "--json"],
    ]


def offer_plugin_update(
    request: dict[str, Any], assessment: dict[str, Any], *, repository_root: Path
) -> dict[str, Any]:
    """Recheck declared subjects, then show inert operator advice or defer."""
    validate_update_request(request)
    mode = request.get("mode", "manual")
    if mode == "off":
        return update_report("offer", "OFF", request, {"hostDispatch": False, "networkRequests": 0})
    if mode in ("safe-auto", "notify"):
        return update_report(
            "offer",
            "UNSUPPORTED",
            request,
            {"reason": "No qualified automatic update/notification boundary", "hostDispatch": False},
        )
    host = request.get("host", {})
    if host.get("adapterId") != "codex" or not host.get("version"):
        return update_report(
            "offer",
            "UNSUPPORTED",
            request,
            {
                "reason": "No documented manual native shape mapped for this declared host",
                "hostDispatch": False,
                "installationEligibility": "UNQUALIFIED",
            },
        )
    validate_update_report(assessment)
    require_update(
        assessment["action"] == "assess"
        and assessment["status"] == "ASSESSED"
        and assessment["details"].get("assessmentComplete") is True,
        "offer needs a complete explicit assessment",
    )
    require_update(assessment["requestDigest"] == canonical_digest(request), "assessment policy changed")
    target = _target(request, assessment)
    if target["sourceCommit"] is None:
        return update_report(
            "offer",
            "UNKNOWN",
            request,
            {
                "reason": "TARGET_COMMIT_UNRESOLVED: bind a separately observed exact commit before offering commands",
                "target": target,
                "assessmentTrust": "DECLARED_LOCAL_REPORT_NOT_AUTHORITY",
                "installationEligibility": "UNQUALIFIED",
                "hostDispatch": False,
            },
            {"assessmentDigest": canonical_digest(assessment)},
        )
    subjects, plans = _assessment_subjects(assessment)
    _recheck_subjects(repository_root, subjects)
    deferred = [plan.get("lifecycle", {}).get("action") for plan in plans]
    if any(action not in ("PROPOSE_UNAPPLIED_EDITS_AND_REVIEW", "PRESERVE_IMMUTABLE_HISTORY") for action in deferred):
        return update_report(
            "offer",
            "UNKNOWN",
            request,
            {
                "reason": "DEFER_ACTIVATION: active or unqualified state boundary",
                "target": target,
                "installationEligibility": "UNQUALIFIED",
                "hostDispatch": False,
            },
            {"assessmentDigest": canonical_digest(assessment)},
        )
    return update_report(
        "offer",
        "OFFERED",
        request,
        {
            "target": target,
            "host": host,
            "hostIdentityProvenance": "DECLARED",
            "commands": _manual_codex_commands(target["version"]),
            "commandStatus": "INERT_OPERATOR_RECIPE_NOT_QUALIFIED_EXECUTION",
            "assessmentTrust": "DECLARED_LOCAL_REPORT_NOT_AUTHORITY",
            "installationEligibility": "UNQUALIFIED",
            "hostDispatch": False,
            "globalEffectScope": "UNKNOWN_BEYOND_EXPLICIT_INVENTORY",
            "upstreamTagRecheckRequired": True,
            "separateNativePermissionRequired": True,
            "activation": "RESTART_AND_OBSERVE_SEPARATELY",
            "recovery": "UNKNOWN_NO_BLIND_RETRY_OR_CACHE_RETENTION_PROMISE",
            "planGaps": [plan.get("gaps", []) for plan in plans],
            "assessedFilesRechecked": len(subjects),
            "compatibilityGuarantee": "NONE; manual recipe is not an install recommendation",
        },
        {"assessmentDigest": canonical_digest(assessment)},
    )


def refuse_plugin_install(request: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    """No current host operation is qualified; never try a generic launcher."""
    validate_update_request(request)
    if request.get("mode") == "off":
        return update_report("install", "OFF", request, {"hostDispatch": False})
    validate_update_report(offer)
    require_update(offer["action"] == "offer", "installation input is not an offer")
    require_update(offer["requestDigest"] == canonical_digest(request), "offer policy changed")
    return update_report(
        "install",
        "UNSUPPORTED",
        request,
        {
            "reason": "NATIVE_INSTALL_UNQUALIFIED",
            "hostDispatch": False,
            "safeAutoSupported": False,
            "scopeQualification": "UNAVAILABLE",
            "activation": "NOT_PERFORMED",
            "retry": "NONE",
            "nextAction": "Use separately authorized host-owned procedure; reconcile any external effect",
        },
        {"offerDigest": canonical_digest(offer)},
    )


def reconcile_plugin_update(request: dict[str, Any]) -> dict[str, Any]:
    identities = observe_update_identities(request)
    status = "DRIFT" if identities["labelComparison"] == "DRIFT" else "UNKNOWN"
    return update_report(
        "reconcile",
        status,
        request,
        {
            "identities": identities,
            "hostDispatch": False,
            "activation": "NOT_ATTESTED_BY_CALLER_LABELS",
            "planMutation": False,
            "retry": "NONE",
            "nextAction": "Preserve active authority and qualify loaded instructions/runtime before continuing",
        },
    )
