"""Convert untrusted planning inputs into reviewed ALK draft artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.planning import validate_plan_manifest

PLANNING_IMPORT_RESULT_SCHEMA = "agent-planning-import-result.v1"
PLANNING_IMPORT_VALIDATION_SCHEMA = "agent-planning-import-validation.v1"
SKILL_IMPROVEMENT_PROPOSAL_SCHEMA = "agent-skill-improvement-proposal.v1"
SKILL_IMPROVEMENT_PROPOSAL_VALIDATION_SCHEMA = "agent-skill-improvement-proposal-validation.v1"

DEFAULT_MAX_INPUT_BYTES = 32768
DEFAULT_TARGET_TOKENS = 4096
MAX_REQUIREMENTS = 8
MAX_REQUIREMENT_CHARS = 180

LOCAL_PATH_PATTERNS = (
    re.compile(r"/" + r"Users/[^\s`'\"<>]+"),
    re.compile(r"/" + r"Volumes/[^\s`'\"<>]+"),
    re.compile(r"[A-Za-z]:[\\/][^\s`'\"<>]+"),
)
SECRET_MARKERS = (
    "BEGIN " + "OPENSSH PRIVATE KEY",
    "BEGIN " + "RSA PRIVATE KEY",
    "AWS_" + "SECRET_ACCESS_KEY",
    "GITHUB_" + "TOKEN=",
)


def import_planning_input(
    source_path: Path,
    *,
    package_id: str = "imported-plan",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    dialect_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a draft ALK candidate from an explicit untrusted input file."""

    _check_positive_cap(max_input_bytes, "maxInputBytes")
    _check_positive_cap(target_tokens, "targetTokens")
    blockers: list[dict[str, Any]] = []
    if not source_path.is_file():
        blockers.append({"code": "planning-import-source-missing", "sourceLabel": source_path.name})
        data = b""
    else:
        size = source_path.stat().st_size
        if size > max_input_bytes:
            blockers.append({"code": "planning-import-input-cap-exceeded", "inputBytes": size, "cap": max_input_bytes})
            data = b""
        else:
            data = source_path.read_bytes()
    return _build_import_result(
        data,
        source_label=source_path.name,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=dialect_profile,
        blockers=blockers,
    )


def import_planning_text(
    text: str,
    *,
    source_label: str = "inline-task",
    package_id: str = "imported-plan",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    dialect_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a draft ALK candidate from explicit untrusted inline text."""

    _check_positive_cap(max_input_bytes, "maxInputBytes")
    _check_positive_cap(target_tokens, "targetTokens")
    if not isinstance(text, str):
        raise LifecycleError("invalid-planning-text", "text must be a string")
    data = text.encode("utf-8")
    blockers: list[dict[str, Any]] = []
    if len(data) > max_input_bytes:
        blockers.append({"code": "planning-import-input-cap-exceeded", "inputBytes": len(data), "cap": max_input_bytes})
        data = b""
    return _build_import_result(
        data,
        source_label=source_label,
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=dialect_profile,
        blockers=blockers,
    )


def _build_import_result(
    data: bytes,
    *,
    source_label: str,
    package_id: str,
    max_input_bytes: int,
    target_tokens: int,
    dialect_profile: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    native_dialect_profile_digest = _profile_digest(dialect_profile)
    text = _decode_text(data, blockers) if data and len(data) <= max_input_bytes else ""
    blockers.extend(_content_blockers(text))
    candidate = (
        _candidate_plan(
            text,
            data,
            package_id=package_id,
            source_label=source_label,
            native_dialect_profile_digest=native_dialect_profile_digest,
            dialect_profile=dialect_profile,
        )
        if text and not blockers
        else None
    )
    if text and candidate is None and not blockers:
        blockers.append({"code": "planning-import-requirements-missing"})
    body = {
        "schemaVersion": PLANNING_IMPORT_RESULT_SCHEMA,
        "status": "PASS",
        "enabledByDefault": False,
        "activationMode": "explicit-command",
        "sourceTrusted": False,
        "candidateLifecycleStatus": "DRAFT_REQUIRES_REVIEW" if candidate else "BLOCKED",
        "reviewGates": ["plan check", "independent audit", "freeze approval"],
        "resourceCaps": {"maxInputBytes": max_input_bytes, "targetTokens": target_tokens},
        "source": {
            "label": source_label,
            "digest": sha256_hex(data),
            "inputBytes": len(data),
        },
        "nativeDialectProfileDigest": native_dialect_profile_digest,
        "dialectProfile": _dialect_profile_summary(dialect_profile),
        "candidatePlan": candidate,
        "requiresReview": True,
        "auditRequired": True,
        "freezeBlocked": True,
        "blockers": blockers,
    }
    body["estimatedTokens"] = estimate_tokens(body)
    if body["estimatedTokens"] > target_tokens:
        body["blockers"].append(
            {
                "code": "planning-import-target-tokens-exceeded",
                "estimatedTokens": body["estimatedTokens"],
                "targetTokens": target_tokens,
            }
        )
    if body["blockers"]:
        body["status"] = "FAIL"
    return {**body, "importDigest": canonical_digest(body)}


def validate_import_result(result: dict[str, Any]) -> dict[str, Any]:
    """Verify that an import result cannot bypass draft, audit or freeze gates."""

    blockers: list[dict[str, Any]] = []
    if result.get("schemaVersion") != PLANNING_IMPORT_RESULT_SCHEMA:
        blockers.append({"code": "planning-import-schema-invalid"})
    if result.get("enabledByDefault") is not False:
        blockers.append({"code": "planning-import-default-enabled"})
    if result.get("activationMode") != "explicit-command":
        blockers.append({"code": "planning-import-activation-mode"})
    if result.get("sourceTrusted") is not False:
        blockers.append({"code": "planning-import-source-trust"})
    if result.get("requiresReview") is not True:
        blockers.append({"code": "planning-import-review-not-required"})
    if result.get("auditRequired") is not True:
        blockers.append({"code": "planning-import-audit-not-required"})
    if result.get("freezeBlocked") is not True:
        blockers.append({"code": "planning-import-freeze-not-blocked"})
    if result.get("status") != "PASS":
        blockers.append({"code": "planning-import-result-not-pass"})
    candidate = result.get("candidatePlan")
    candidate_digest = None
    if not isinstance(candidate, dict):
        blockers.append({"code": "planning-import-candidate-missing"})
    else:
        candidate_digest = canonical_digest(candidate)
        if candidate.get("schemaVersion") != "agent-plan-manifest.v1":
            blockers.append({"code": "planning-import-candidate-schema"})
        if candidate.get("status") != "DRAFT":
            blockers.append({"code": "planning-import-candidate-not-draft", "status": candidate.get("status")})
        import_state = candidate.get("importState") if isinstance(candidate.get("importState"), dict) else {}
        if import_state.get("requiresReview") is not True:
            blockers.append({"code": "planning-import-candidate-review-not-required"})
        if import_state.get("auditRequired") is not True:
            blockers.append({"code": "planning-import-candidate-audit-not-required"})
        if import_state.get("freezeBlocked") is not True:
            blockers.append({"code": "planning-import-candidate-freeze-not-blocked"})
        profile_digest = result.get("nativeDialectProfileDigest")
        candidate_profile_digest = import_state.get("nativeDialectProfileDigest")
        if profile_digest is not None:
            if not _is_digest(profile_digest):
                blockers.append({"code": "planning-import-dialect-profile-digest-invalid"})
            if candidate_profile_digest != profile_digest:
                blockers.append({"code": "planning-import-dialect-profile-digest-mismatch"})
        try:
            validate_plan_manifest(candidate)
        except LifecycleError as exc:
            blockers.append({"code": "planning-import-candidate-invalid", "reason": exc.code})
    expected_digest = canonical_digest({key: value for key, value in result.items() if key != "importDigest"})
    if result.get("importDigest") != expected_digest:
        blockers.append({"code": "planning-import-digest-mismatch"})
    body = {
        "schemaVersion": PLANNING_IMPORT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "candidateDigest": candidate_digest,
        "freezeBlocked": result.get("freezeBlocked") is True,
        "auditRequired": result.get("auditRequired") is True,
        "requiresReview": result.get("requiresReview") is True,
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def validate_skill_improvement_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Validate a reviewed proposal record without applying skill edits."""

    blockers: list[dict[str, Any]] = []
    if proposal.get("schemaVersion") != SKILL_IMPROVEMENT_PROPOSAL_SCHEMA:
        blockers.append({"code": "skill-proposal-schema-invalid"})
    for key in ("proposalId", "affectedSkill", "rationale", "expectedBehavior"):
        if not isinstance(proposal.get(key), str) or not proposal.get(key, "").strip():
            blockers.append({"code": "skill-proposal-field-missing", "field": key})
    if proposal.get("status") != "PROPOSED":
        blockers.append({"code": "skill-proposal-status-invalid", "status": proposal.get("status")})
    if proposal.get("requiresReview") is not True:
        blockers.append({"code": "skill-proposal-review-not-required"})
    if proposal.get("autoApply") is not False:
        blockers.append({"code": "skill-proposal-auto-apply"})
    if proposal.get("applied") is not False:
        blockers.append({"code": "skill-proposal-already-applied"})
    tests = proposal.get("requiredTests")
    if not isinstance(tests, list) or not tests or any(not isinstance(item, str) or not item.strip() for item in tests):
        blockers.append({"code": "skill-proposal-tests-invalid"})
    affected_skill = proposal.get("affectedSkill")
    if isinstance(affected_skill, str) and _contains_sensitive_marker(affected_skill):
        blockers.append({"code": "skill-proposal-skill-name-invalid"})
    body = {
        "schemaVersion": SKILL_IMPROVEMENT_PROPOSAL_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "proposalId": proposal.get("proposalId"),
        "requiresReview": proposal.get("requiresReview") is True,
        "autoApply": proposal.get("autoApply"),
        "applied": proposal.get("applied"),
        "blockers": blockers,
        "proposalDigest": canonical_digest(proposal),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_import_validation_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "PASS":
        raise LifecycleError("planning-import-validation-failed", "planning import validation failed", {"validation": payload})
    return payload


def require_skill_proposal_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "PASS":
        raise LifecycleError("skill-proposal-validation-failed", "skill proposal validation failed", {"validation": payload})
    return payload


def _candidate_plan(
    text: str,
    data: bytes,
    *,
    package_id: str,
    source_label: str,
    native_dialect_profile_digest: str | None,
    dialect_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    parsed = _parse_structured_input(data)
    title = _extract_title(text, parsed)
    requirements = _extract_requirements(text, parsed)
    if not requirements:
        return None
    source_digest = sha256_hex(data)
    criteria = [
        {
            "id": f"AC-IMPORT-{index + 1}",
            "requirementIds": [requirement["id"]],
            "evidenceIds": [f"EV-IMPORT-{index + 1}"],
            "statement": f"Imported draft requirement {index + 1} is reviewed before freeze.",
        }
        for index, requirement in enumerate(requirements)
    ]
    evidence = [
        {
            "id": f"EV-IMPORT-{index + 1}",
            "description": "Independent review evidence for imported draft content.",
        }
        for index, _ in enumerate(requirements)
    ]
    return {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "DRAFT",
        "planRevision": 1,
        "package": {
            "id": _safe_identifier(package_id) or "imported-plan",
            "title": title,
            "workspaceRoot": ".",
            "artifactRoot": "imported",
            "root": ".",
            "planArtifactRoot": "imported",
        },
        "author": {"id": "planning-import", "surface": "agent-lifecycle", "runId": source_digest[:16]},
        "baseRevision": {"ref": "UNRESOLVED", "sha": "UNRESOLVED"},
        "importState": {
            "sourceLabel": source_label,
            "sourceDigest": source_digest,
            "nativeDialectProfileDigest": native_dialect_profile_digest,
            "dialect": _dialect_profile_summary(dialect_profile),
            "requiresReview": True,
            "auditRequired": True,
            "freezeBlocked": True,
        },
        "specification": {
            "tier": "S2",
            "intent": "to-be",
            "status": "DRAFT",
            "source": "imported-input",
            "requirements": requirements,
        },
        "readOnly": [],
        "forbiddenWrites": [".git"],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-IMPORT-REVIEW",
                "title": "Review imported draft",
                "owner": "import-reviewer",
                "dependsOn": [],
                "writes": [],
                "acceptanceIds": [item["id"] for item in criteria],
                "evidenceIds": [item["id"] for item in evidence],
            }
        ],
        "acceptance": {
            "criteria": criteria,
            "evidence": evidence,
            "releaseGate": "Imported drafts require ALK plan review and explicit freeze before implementation.",
            "qualityFloor": "Imported content cannot replace source-of-truth ALK artifacts.",
        },
    }


def _parse_structured_input(data: bytes) -> dict[str, Any] | None:
    try:
        return load_json_object(data, label="planning import")
    except LifecycleError:
        return None


def _extract_title(text: str, parsed: dict[str, Any] | None) -> str:
    if parsed is not None:
        title = parsed.get("title")
        if isinstance(title, str) and title.strip():
            return _clean_line(title, limit=96)
        package = parsed.get("package") if isinstance(parsed.get("package"), dict) else {}
        package_title = package.get("title")
        if isinstance(package_title, str) and package_title.strip():
            return _clean_line(package_title, limit=96)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return _clean_line(stripped.lstrip("#").strip(), limit=96)
    return "Imported draft plan"


def _extract_requirements(text: str, parsed: dict[str, Any] | None) -> list[dict[str, str]]:
    extracted: list[str] = []
    if parsed is not None:
        raw_requirements = parsed.get("requirements")
        if not isinstance(raw_requirements, list):
            spec = parsed.get("specification") if isinstance(parsed.get("specification"), dict) else {}
            raw_requirements = spec.get("requirements")
        if isinstance(raw_requirements, list):
            for item in raw_requirements:
                if isinstance(item, str):
                    extracted.append(item)
                elif isinstance(item, dict) and isinstance(item.get("description"), str):
                    extracted.append(item["description"])
    if not extracted:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- ", "* ")):
                extracted.append(stripped[2:])
            elif re.match(r"^\d+\.\s+", stripped):
                extracted.append(re.sub(r"^\d+\.\s+", "", stripped))
    if not extracted:
        fallback = " ".join(line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#"))
        if fallback:
            extracted.append(fallback)
    cleaned = [_clean_line(item, limit=MAX_REQUIREMENT_CHARS) for item in extracted if item.strip()]
    return [{"id": f"R-IMPORT-{index + 1}", "description": item} for index, item in enumerate(cleaned[:MAX_REQUIREMENTS])]


def _decode_text(data: bytes, blockers: list[dict[str, Any]]) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        blockers.append({"code": "planning-import-decode-failed"})
        return ""


def _content_blockers(text: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for pattern in LOCAL_PATH_PATTERNS:
        if pattern.search(text):
            blockers.append({"code": "planning-import-local-path"})
            break
    upper = text.upper()
    for marker in SECRET_MARKERS:
        if marker in upper:
            blockers.append({"code": "planning-import-secret-marker"})
            break
    return blockers


def _profile_digest(profile: dict[str, Any] | None) -> str | None:
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise LifecycleError("invalid-dialect-profile", "dialect_profile must be an object")
    digest = profile.get("profileDigest")
    if isinstance(digest, str) and _is_digest(digest):
        expected = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
        if digest != expected:
            raise LifecycleError("invalid-dialect-profile", "dialect profileDigest does not match profile")
        return digest
    return canonical_digest(profile)


def _dialect_profile_summary(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "schemaVersion": profile.get("schemaVersion"),
        "dialectId": profile.get("dialectId"),
        "dialectKind": profile.get("dialectKind"),
        "sourceTrusted": profile.get("sourceTrusted"),
        "profileDigest": _profile_digest(profile),
    }


def _contains_sensitive_marker(value: str) -> bool:
    return bool(_content_blockers(value))


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _safe_identifier(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9_.-]+", "-", lowered).strip("-")[:80]


def _clean_line(value: str, *, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    for pattern in LOCAL_PATH_PATTERNS:
        cleaned = pattern.sub("[redacted-path]", cleaned)
    return cleaned[:limit]


def _check_positive_cap(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LifecycleError("invalid-resource-cap", f"{field} must be a positive integer", {"field": field})
