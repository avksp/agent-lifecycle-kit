"""Generic external dialect import pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.imports.dialect_profiles import (
    DEFAULT_PROFILE_ID,
    external_dialect_profile,
    require_external_profile_pass,
    validate_external_dialect_profile,
)
from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    PLANNING_IMPORT_RESULT_SCHEMA,
    validate_import_result,
)
from agent_lifecycle.planning import validate_plan_manifest

EXTERNAL_IMPORT_VALIDATION_SCHEMA = "agent-external-dialect-import-validation.v1"
MAX_REQUIREMENTS = 8
MAX_REQUIREMENT_CHARS = 180

_POSIX_USER_PREFIX = "/" "Users" "/"
_POSIX_VOLUME_PREFIX = "/" "Volumes" "/"
_LOCAL_PATH_RE = re.compile(
    r"(" + re.escape(_POSIX_USER_PREFIX) + r"|" + re.escape(_POSIX_VOLUME_PREFIX) + r"|[A-Za-z]:[\\/])\S+"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*)\s*[:=]\s*[^\s,}\]]+"
)


def import_external_dialect(
    source_path: Path,
    *,
    family: str,
    profile_id: str = DEFAULT_PROFILE_ID,
    package_id: str = "external-dialect-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    """Map a generic external dialect file into an untrusted ALK draft."""

    _check_positive_cap(max_input_bytes, "maxInputBytes")
    _check_positive_cap(target_tokens, "targetTokens")
    profile = external_dialect_profile(
        family,
        profile_id=profile_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )
    require_external_profile_pass(validate_external_dialect_profile(profile))
    blockers: list[dict[str, Any]] = []
    data = _read_source(source_path, max_input_bytes=max_input_bytes, blockers=blockers)
    text = _decode_source(data, blockers) if data else ""
    parsed = _parse_input(text, blockers) if text else {}
    mapping = _map_family(family, parsed, text, blockers)
    candidate = _candidate_plan(
        mapping,
        package_id=package_id,
        source_label=source_path.name,
        source_digest=sha256_hex(data),
        profile=profile,
    ) if not blockers else None
    if candidate is None and not blockers:
        blockers.append({"code": "external-dialect-requirements-missing"})
    body = {
        "schemaVersion": PLANNING_IMPORT_RESULT_SCHEMA,
        "status": "PASS",
        "enabledByDefault": False,
        "activationMode": "explicit-command",
        "sourceTrusted": False,
        "candidateLifecycleStatus": "DRAFT_REQUIRES_REVIEW" if candidate else "BLOCKED",
        "reviewGates": ["plan check", "independent audit", "freeze approval"],
        "resourceCaps": {"maxInputBytes": max_input_bytes, "targetTokens": target_tokens},
        "source": {"label": source_path.name, "digest": sha256_hex(data), "inputBytes": len(data)},
        "nativeDialectProfileDigest": profile["profileDigest"],
        "dialectProfile": _profile_summary(profile),
        "externalDialect": _external_summary(mapping),
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
                "code": "external-dialect-target-tokens-exceeded",
                "estimatedTokens": body["estimatedTokens"],
                "targetTokens": target_tokens,
            }
        )
    if body["blockers"]:
        body["status"] = "FAIL"
    return {**body, "importDigest": canonical_digest(body)}


def validate_external_import_result(result: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    planning_validation = validate_import_result(result)
    if planning_validation.get("status") != "PASS":
        blockers.extend(planning_validation.get("blockers", []))
    external = result.get("externalDialect")
    if not isinstance(external, dict):
        blockers.append({"code": "external-dialect-summary-missing"})
    else:
        if external.get("sourceTrusted") is not False:
            blockers.append({"code": "external-dialect-source-trusted"})
        if external.get("family") not in {"workflow", "agent"}:
            blockers.append({"code": "external-dialect-family-invalid"})
        if external.get("executesInput") is not False:
            blockers.append({"code": "external-dialect-execution-enabled"})
        if external.get("portableProviderDefaults") is not False:
            blockers.append({"code": "external-dialect-provider-default"})
    candidate = result.get("candidatePlan")
    if isinstance(candidate, dict):
        external_state = candidate.get("externalImport") if isinstance(candidate.get("externalImport"), dict) else {}
        if external_state.get("sourceTrusted") is not False:
            blockers.append({"code": "external-dialect-candidate-source-trusted"})
        if external_state.get("executesInput") is not False:
            blockers.append({"code": "external-dialect-candidate-executes-input"})
        try:
            validate_plan_manifest(candidate)
        except LifecycleError as exc:
            blockers.append({"code": "external-dialect-candidate-invalid", "reason": exc.code})
    body = {
        "schemaVersion": EXTERNAL_IMPORT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "family": external.get("family") if isinstance(external, dict) else None,
        "candidateDigest": canonical_digest(candidate) if isinstance(candidate, dict) else None,
        "requiresReview": result.get("requiresReview") is True,
        "auditRequired": result.get("auditRequired") is True,
        "freezeBlocked": result.get("freezeBlocked") is True,
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_external_import_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "external-dialect-import-validation-failed",
            "external dialect import validation failed",
            {"validation": validation},
        )
    return validation


def _read_source(source_path: Path, *, max_input_bytes: int, blockers: list[dict[str, Any]]) -> bytes:
    if not source_path.is_file():
        blockers.append({"code": "external-dialect-source-missing", "sourceLabel": source_path.name})
        return b""
    size = source_path.stat().st_size
    if size > max_input_bytes:
        blockers.append({"code": "external-dialect-input-cap-exceeded", "inputBytes": size, "cap": max_input_bytes})
        return b""
    return source_path.read_bytes()


def _decode_source(data: bytes, blockers: list[dict[str, Any]]) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        blockers.append({"code": "external-dialect-decode-failed"})
        return ""


def _parse_input(text: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _parse_yaml_like(text)
    if not isinstance(parsed, dict):
        blockers.append({"code": "external-dialect-input-not-object"})
        return {}
    return parsed


def _parse_yaml_like(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_key = _clean_key(key)
            parsed[current_key] = _parse_scalar(value.strip()) if value.strip() else []
            continue
        if current_key and stripped.startswith("- "):
            value = stripped[2:].strip()
            if not isinstance(parsed.get(current_key), list):
                parsed[current_key] = []
            parsed[current_key].append(_parse_inline_mapping(value))
            continue
        if current_key and ":" in stripped:
            key, value = stripped.split(":", 1)
            if not isinstance(parsed.get(current_key), dict):
                parsed[current_key] = {}
            nested_key = key.strip() if current_key in {"env", "environment"} else _clean_key(key)
            parsed[current_key][nested_key] = _parse_scalar(value.strip())
    return parsed


def _parse_inline_mapping(value: str) -> Any:
    if ":" not in value:
        return _parse_scalar(value)
    key, raw = value.split(":", 1)
    return {_clean_key(key): _parse_scalar(raw.strip())}


def _parse_scalar(value: str) -> Any:
    stripped = value.strip().strip("\"'")
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    return stripped


def _map_family(family: str, parsed: dict[str, Any], text: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    if family == "workflow":
        return _map_workflow(parsed, text)
    if family == "agent":
        return _map_agent(parsed, text)
    blockers.append({"code": "external-dialect-family-invalid", "family": family})
    return {}


def _map_workflow(parsed: dict[str, Any], text: str) -> dict[str, Any]:
    steps = _list_from(parsed, "steps", "jobs", "tasks")
    validations = _list_from(parsed, "validation", "validations", "checks")
    requirements = [
        f"Review imported workflow step {index + 1}: {_safe_summary(step)}."
        for index, step in enumerate(steps[:MAX_REQUIREMENTS])
    ]
    if not requirements:
        requirements = _requirements_from_lines(text, prefix="Review imported workflow instruction")
    return {
        "family": "workflow",
        "title": _title(parsed, "Imported workflow draft"),
        "requirements": requirements,
        "workHints": [{"kind": "workflow-step", "summary": _safe_summary(step)} for step in steps[:MAX_REQUIREMENTS]],
        "validationHints": [_safe_summary(item) for item in validations[:MAX_REQUIREMENTS]],
        "hostLocalHints": {},
        "redactions": _redaction_summary(parsed),
    }


def _map_agent(parsed: dict[str, Any], text: str) -> dict[str, Any]:
    policies = _list_from(parsed, "policies", "policy", "rules", "instructions")
    requirements = []
    role = _first_string(parsed, "role", "description", "purpose")
    if role:
        requirements.append(f"Review imported agent role hint before converting it into ALK task scope: {_safe_summary(role)}.")
    requirements.extend(f"Review imported agent policy hint {index + 1}: {_safe_summary(item)}." for index, item in enumerate(policies[:MAX_REQUIREMENTS]))
    if not requirements:
        requirements = _requirements_from_lines(text, prefix="Review imported agent instruction")
    return {
        "family": "agent",
        "title": _title(parsed, "Imported agent draft"),
        "requirements": requirements[:MAX_REQUIREMENTS],
        "workHints": [],
        "validationHints": [],
        "hostLocalHints": _host_local_hints(parsed),
        "redactions": _redaction_summary(parsed),
    }


def _candidate_plan(
    mapping: dict[str, Any],
    *,
    package_id: str,
    source_label: str,
    source_digest: str,
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    requirements = [
        {"id": f"R-EXT-{index + 1}", "description": _truncate(item, MAX_REQUIREMENT_CHARS)}
        for index, item in enumerate(mapping.get("requirements", [])[:MAX_REQUIREMENTS])
        if isinstance(item, str) and item.strip()
    ]
    if not requirements:
        return None
    criteria = [
        {
            "id": f"AC-EXT-{index + 1}",
            "requirementIds": [requirement["id"]],
            "evidenceIds": [f"EV-EXT-{index + 1}"],
            "statement": f"Imported {mapping['family']} requirement {index + 1} is reviewed before freeze.",
        }
        for index, requirement in enumerate(requirements)
    ]
    evidence = [
        {"id": f"EV-EXT-{index + 1}", "description": "Independent review evidence for imported external dialect content."}
        for index, _ in enumerate(requirements)
    ]
    return {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "DRAFT",
        "planRevision": 1,
        "package": {
            "id": _safe_identifier(package_id) or "external-dialect-import",
            "title": mapping["title"],
            "workspaceRoot": ".",
            "artifactRoot": "imported",
            "root": ".",
            "planArtifactRoot": "imported",
        },
        "author": {"id": "external-dialect-import", "surface": "agent-lifecycle", "runId": source_digest[:16]},
        "baseRevision": {"ref": "UNRESOLVED", "sha": "UNRESOLVED"},
        "importState": {
            "sourceLabel": source_label,
            "sourceDigest": source_digest,
            "nativeDialectProfileDigest": profile["profileDigest"],
            "dialect": _profile_summary(profile),
            "requiresReview": True,
            "auditRequired": True,
            "freezeBlocked": True,
        },
        "externalImport": {
            "family": mapping["family"],
            "sourceTrusted": False,
            "executesInput": False,
            "portableProviderDefaults": False,
            "workHints": mapping.get("workHints", []),
            "validationHints": mapping.get("validationHints", []),
            "hostLocalHints": mapping.get("hostLocalHints", {}),
            "redactions": mapping.get("redactions", {}),
        },
        "specification": {
            "tier": "S2",
            "intent": "to-be",
            "status": "DRAFT",
            "source": "external-dialect-import",
            "requirements": requirements,
        },
        "readOnly": [],
        "forbiddenWrites": [".git"],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-EXTERNAL-REVIEW",
                "title": "Review imported external draft",
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
            "releaseGate": "External dialect imports require ALK plan review and explicit freeze before implementation.",
            "qualityFloor": "Imported workflow or agent content cannot replace source-of-truth ALK artifacts.",
        },
    }


def _external_summary(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": mapping.get("family"),
        "sourceTrusted": False,
        "executesInput": False,
        "portableProviderDefaults": False,
        "workHintCount": len(mapping.get("workHints", [])),
        "validationHintCount": len(mapping.get("validationHints", [])),
        "hostLocalHintKeys": sorted(mapping.get("hostLocalHints", {}).keys()),
        "redactions": mapping.get("redactions", {}),
    }


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": profile.get("schemaVersion"),
        "dialectId": profile.get("dialectId"),
        "dialectKind": profile.get("dialectKind"),
        "family": profile.get("family"),
        "profileId": profile.get("profileId"),
        "sourceTrusted": profile.get("sourceTrusted"),
        "profileDigest": profile.get("profileDigest"),
    }


def _host_local_hints(parsed: dict[str, Any]) -> dict[str, Any]:
    hints: dict[str, Any] = {}
    for key in ("provider", "model", "auth"):
        value = parsed.get(key)
        if value not in (None, "", []):
            hints[key] = _redacted_value(value)
    env = parsed.get("environment", parsed.get("env", {}))
    if isinstance(env, dict):
        hints["environmentKeys"] = sorted(str(key) for key in env)
    tools = _list_from(parsed, "tools", "tooling", "capabilities")
    if tools:
        hints["toolHints"] = [_redacted_value(item) for item in tools]
    return hints


def _redacted_value(value: Any) -> dict[str, Any]:
    return {"redacted": True, "valueDigest": canonical_digest({"value": str(value)})}


def _redaction_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    keys = []
    for key in parsed:
        lowered = str(key).lower()
        if lowered in {"provider", "model", "auth", "env", "environment", "tools"} or any(marker in lowered for marker in ("token", "secret", "password")):
            keys.append(str(key))
    return {"redactedOrHostLocalKeys": sorted(keys), "secretValuesStored": False}


def _requirements_from_lines(text: str, *, prefix: str) -> list[str]:
    requirements = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            requirements.append(f"{prefix}: {_safe_summary(stripped[2:])}.")
        elif re.match(r"^\d+\.\s+", stripped):
            numbered_text = re.sub(r"^\d+\.\s+", "", stripped)
            requirements.append(f"{prefix}: {_safe_summary(numbered_text)}.")
    return requirements[:MAX_REQUIREMENTS]


def _list_from(parsed: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = parsed.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        if isinstance(value, str) and value.strip():
            return [value]
    return []


def _first_string(parsed: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _title(parsed: dict[str, Any], fallback: str) -> str:
    value = _first_string(parsed, "title", "name", "workflow", "agent")
    return _safe_summary(value) if value else fallback


def _safe_summary(value: Any) -> str:
    if isinstance(value, dict):
        text = " ".join(f"{_clean_key(str(key))} {_safe_summary(item)}" for key, item in sorted(value.items()))
    else:
        text = str(value)
    text = _LOCAL_PATH_RE.sub("[redacted-path]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1=[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _truncate(text, MAX_REQUIREMENT_CHARS)


def _safe_identifier(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9_.-]+", "-", lowered).strip("-")[:80]


def _clean_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()


def _truncate(value: str, limit: int) -> str:
    return value[:limit]


def _check_positive_cap(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LifecycleError("invalid-resource-cap", f"{field} must be a positive integer", {"field": field})
