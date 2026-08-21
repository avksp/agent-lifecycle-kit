"""Disposable evidence indexes over existing lifecycle artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file, resolve_repository_file
from agent_lifecycle.contracts.token_estimation import estimate_tokens

EVIDENCE_INDEX_SCHEMA = "agent-evidence-index.v1"
EVIDENCE_INDEX_VALIDATION_SCHEMA = "agent-evidence-index-validation.v1"
EVIDENCE_SEARCH_SUMMARY_SCHEMA = "agent-evidence-search-summary.v1"

DEFAULT_MAX_ARTIFACTS = 64
DEFAULT_MAX_INPUT_BYTES = 65536
DEFAULT_TARGET_TOKENS = 2048
SUMMARY_KEYS = ("schemaVersion", "status", "packageId", "runId", "taskId", "operationId", "adapterId", "host")
REDACTION_MARKERS = (
    ("/" + "Users/").encode("utf-8"),
    ("/" + "Volumes/").encode("utf-8"),
    ("BEGIN " + "OPENSSH PRIVATE KEY").encode("utf-8"),
    ("BEGIN " + "RSA PRIVATE KEY").encode("utf-8"),
    ("AWS_" + "SECRET_ACCESS_KEY").encode("utf-8"),
)


def build_evidence_index(
    project_root: Path,
    artifact_paths: list[str],
    *,
    max_artifacts: int = DEFAULT_MAX_ARTIFACTS,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    """Build a compact optional index from explicit repository-relative artifacts."""

    blockers: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    _check_positive_cap(max_artifacts, "maxArtifacts")
    _check_positive_cap(max_input_bytes, "maxInputBytes")
    _check_positive_cap(target_tokens, "targetTokens")
    if not artifact_paths:
        blockers.append({"code": "evidence-index-artifacts-missing"})
    if len(artifact_paths) > max_artifacts:
        blockers.append({"code": "evidence-index-artifact-cap-exceeded", "requested": len(artifact_paths), "cap": max_artifacts})
    total_bytes = 0
    root = project_root.resolve()
    for index, raw_path in enumerate(artifact_paths[:max_artifacts]):
        try:
            repo_path = normalize_repo_path(raw_path, label="artifact")
        except LifecycleError as exc:
            blockers.append({"code": "evidence-index-artifact-path-invalid", "index": index, "reason": exc.code})
            continue
        try:
            path = resolve_repository_file(root, repo_path, label="artifact")
        except LifecycleError as exc:
            code = "evidence-index-artifact-symlink" if exc.code == "repository-input-symlink" else "evidence-index-artifact-missing"
            blockers.append({"code": code, "index": index, "path": repo_path, "reason": exc.code})
            continue
        size = path.stat().st_size
        if total_bytes + size > max_input_bytes:
            omitted.append({"path": repo_path, "reason": "maxInputBytes"})
            blockers.append({"code": "evidence-index-input-cap-exceeded", "index": index, "path": repo_path, "cap": max_input_bytes})
            continue
        try:
            data = read_stable_repository_file(
                root,
                repo_path,
                max_bytes=max_input_bytes - total_bytes,
                label="artifact",
            )
        except LifecycleError as exc:
            if exc.code == "repository-input-symlink":
                code = "evidence-index-artifact-symlink"
            elif exc.code == "repository-input-too-large":
                code = "evidence-index-input-cap-exceeded"
            else:
                code = "evidence-index-artifact-read-failed"
            blockers.append({"code": code, "index": index, "path": repo_path, "reason": exc.code})
            continue
        total_bytes += len(data)
        entry = _entry_from_bytes(repo_path, data)
        entries.append(entry)
    body = {
        "schemaVersion": EVIDENCE_INDEX_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "rebuildable": True,
        "enabledByDefault": False,
        "activationMode": "explicit-command",
        "resourceCaps": {
            "maxArtifacts": max_artifacts,
            "maxInputBytes": max_input_bytes,
            "targetTokens": target_tokens,
        },
        "artifactCount": len(entries),
        "inputBytes": min(total_bytes, max_input_bytes),
        "entries": entries,
        "omitted": omitted,
        "blockers": blockers,
    }
    body["estimatedTokens"] = estimate_tokens(body)
    if body["estimatedTokens"] > target_tokens:
        body["blockers"].append(
            {
                "code": "evidence-index-target-tokens-exceeded",
                "estimatedTokens": body["estimatedTokens"],
                "targetTokens": target_tokens,
            }
        )
    if body["blockers"]:
        body["status"] = "FAIL"
    return {**body, "indexDigest": canonical_digest(body)}


def validate_evidence_index(index: dict[str, Any]) -> dict[str, Any]:
    """Validate that an index is optional, rebuildable and not a source of truth."""

    blockers: list[dict[str, Any]] = []
    if index.get("schemaVersion") != EVIDENCE_INDEX_SCHEMA:
        blockers.append({"code": "evidence-index-schema-invalid"})
    if index.get("status") != "PASS":
        blockers.append({"code": "evidence-index-status-not-pass", "status": index.get("status")})
    if index.get("sourceOfTruth") is not False:
        blockers.append({"code": "evidence-index-source-of-truth"})
    if index.get("rebuildable") is not True:
        blockers.append({"code": "evidence-index-not-rebuildable"})
    if index.get("enabledByDefault") is not False:
        blockers.append({"code": "evidence-index-default-enabled"})
    if index.get("activationMode") != "explicit-command":
        blockers.append({"code": "evidence-index-activation-mode"})
    entries = index.get("entries")
    if not isinstance(entries, list):
        blockers.append({"code": "evidence-index-entries-invalid"})
        entries = []
    for item_index, entry in enumerate(entries):
        _validate_entry(entry, item_index, blockers)
    expected_digest = canonical_digest({key: value for key, value in index.items() if key != "indexDigest"})
    if index.get("indexDigest") != expected_digest:
        blockers.append({"code": "evidence-index-digest-mismatch"})
    body = {
        "schemaVersion": EVIDENCE_INDEX_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "artifactCount": len(entries),
        "blockers": blockers,
        "indexDigest": index.get("indexDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def search_evidence_index(
    index: dict[str, Any],
    *,
    query: str = "",
    max_results: int = 8,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    """Return a compact search summary without returning raw artifact content."""

    _check_positive_cap(max_results, "maxResults")
    _check_positive_cap(target_tokens, "targetTokens")
    validation = validate_evidence_index(index)
    entries = index.get("entries") if isinstance(index.get("entries"), list) else []
    matches = _rank_entries(entries, query)[:max_results]
    body = {
        "schemaVersion": EVIDENCE_SEARCH_SUMMARY_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "query": query,
        "resultCount": len(matches),
        "maxResults": max_results,
        "results": [_search_projection(item) for item in matches],
        "omittedResultCount": max(0, len(_rank_entries(entries, query)) - len(matches)),
        "indexDigest": index.get("indexDigest"),
        "blockers": [] if validation["status"] == "PASS" else [{"code": "evidence-index-invalid"}],
    }
    body["estimatedTokens"] = estimate_tokens(body)
    body["targetTokens"] = target_tokens
    if body["estimatedTokens"] > target_tokens:
        body["blockers"].append(
            {
                "code": "evidence-search-target-tokens-exceeded",
                "estimatedTokens": body["estimatedTokens"],
                "targetTokens": target_tokens,
            }
        )
    if body["blockers"]:
        body["status"] = "FAIL"
    return {**body, "summaryDigest": canonical_digest(body)}


def require_evidence_index_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "PASS":
        raise LifecycleError("evidence-index-failed", "evidence index validation failed", {"index": payload})
    return payload


def require_evidence_search_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "PASS":
        raise LifecycleError("evidence-search-failed", "evidence search summary failed", {"summary": payload})
    return payload


def _entry_from_bytes(repo_path: str, data: bytes) -> dict[str, Any]:
    digest = sha256_hex(data)
    payload: dict[str, Any] | None = None
    try:
        payload = load_json_object(data, label=repo_path)
    except LifecycleError:
        payload = None
    redacted = _needs_redaction(data)
    summary = _payload_summary(payload) if payload is not None else {"format": "non-json"}
    schema_version = payload.get("schemaVersion") if isinstance(payload, dict) else None
    recognition = _recognize_schema(schema_version)
    return {
        "sourcePath": repo_path,
        "artifactDigest": digest,
        "artifactType": summary.get("schemaVersion") or summary.get("format") or "unknown",
        "artifactRecognition": recognition,
        "validationStatus": "UNVALIDATED",
        "validatedArtifact": False,
        "redactionStatus": "REDACTED" if redacted else "CLEAR",
        "summary": summary,
    }


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"fieldCount": len(payload)}
    for key in SUMMARY_KEYS:
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
    summary["topLevelKeys"] = sorted(str(key) for key in payload)[:12]
    return summary


def _validate_entry(entry: object, index: int, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(entry, dict):
        blockers.append({"code": "evidence-index-entry-invalid", "index": index})
        return
    for key in (
        "sourcePath",
        "artifactDigest",
        "artifactType",
        "artifactRecognition",
        "validationStatus",
        "validatedArtifact",
        "redactionStatus",
        "summary",
    ):
        if key not in entry:
            blockers.append({"code": "evidence-index-entry-field-missing", "index": index, "field": key})
    try:
        normalize_repo_path(str(entry.get("sourcePath")), label="sourcePath")
    except LifecycleError as exc:
        blockers.append({"code": "evidence-index-entry-path-invalid", "index": index, "reason": exc.code})
    if entry.get("redactionStatus") not in {"CLEAR", "REDACTED"}:
        blockers.append({"code": "evidence-index-entry-redaction-invalid", "index": index})
    if entry.get("artifactRecognition") not in {"RECOGNIZED", "UNKNOWN"}:
        blockers.append({"code": "evidence-index-entry-recognition-invalid", "index": index})
    if entry.get("validationStatus") not in {"SCHEMA_VALIDATED", "UNVALIDATED"}:
        blockers.append({"code": "evidence-index-entry-validation-status-invalid", "index": index})
    if not isinstance(entry.get("validatedArtifact"), bool):
        blockers.append({"code": "evidence-index-entry-validation-flag-invalid", "index": index})
    if entry.get("validatedArtifact") is True and entry.get("validationStatus") != "SCHEMA_VALIDATED":
        blockers.append({"code": "evidence-index-entry-validation-claim-mismatch", "index": index})
    if entry.get("validationStatus") == "SCHEMA_VALIDATED" and entry.get("artifactRecognition") != "RECOGNIZED":
        blockers.append({"code": "evidence-index-entry-unrecognized-validation", "index": index})


def _rank_entries(entries: list[Any], query: str) -> list[dict[str, Any]]:
    valid_entries = [entry for entry in entries if isinstance(entry, dict)]
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return valid_entries
    ranked: list[tuple[int, dict[str, Any]]] = []
    for entry in valid_entries:
        haystack = json.dumps(_search_projection(entry), ensure_ascii=False, sort_keys=True).lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], item[1].get("sourcePath") or ""))
    return [entry for _, entry in ranked]


def _search_projection(entry: dict[str, Any]) -> dict[str, Any]:
    summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    return {
        "sourcePath": entry.get("sourcePath"),
        "artifactType": entry.get("artifactType"),
        "status": summary.get("status"),
        "redactionStatus": entry.get("redactionStatus"),
        "digest": entry.get("artifactDigest"),
        "summary": {key: summary[key] for key in SUMMARY_KEYS if key in summary},
    }


def _needs_redaction(data: bytes) -> bool:
    return any(marker in data for marker in REDACTION_MARKERS)


def _recognize_schema(schema_version: object) -> str:
    if not isinstance(schema_version, str) or not schema_version:
        return "UNKNOWN"
    try:
        get_schema(schema_version)
    except LifecycleError:
        return "UNKNOWN"
    return "RECOGNIZED"


def _check_positive_cap(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LifecycleError("invalid-resource-cap", f"{field} must be a positive integer", {"field": field})
