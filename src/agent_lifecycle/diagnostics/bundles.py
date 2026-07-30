"""Redacted diagnostic bundle export from existing artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex

DIAGNOSTIC_BUNDLE_SCHEMA = "agent-diagnostic-bundle.v1"
SENSITIVE_KEY_FRAGMENTS = ("key", "secret", "token", "password", "authorization", "credential")


def build_diagnostic_bundle(
    *,
    project_root: Path,
    artifact_paths: list[Path],
    max_artifacts: int = 8,
    max_input_bytes: int = 20000,
) -> dict[str, Any]:
    """Build one compact, redacted bundle without treating it as source truth."""

    root = project_root.resolve()
    blockers: list[dict[str, Any]] = []
    if max_artifacts <= 0:
        raise LifecycleError("invalid-diagnostic-bundle-cap", "max artifacts must be positive")
    if max_input_bytes <= 0:
        raise LifecycleError("invalid-diagnostic-bundle-cap", "max input bytes must be positive")
    if not artifact_paths:
        blockers.append({"code": "diagnostic-bundle-artifacts-missing", "message": "at least one artifact is required"})
    if len(artifact_paths) > max_artifacts:
        blockers.append({"code": "diagnostic-bundle-artifact-cap-exceeded", "count": len(artifact_paths), "maxArtifacts": max_artifacts})
    artifacts: list[dict[str, Any]] = []
    for raw_path in artifact_paths[:max_artifacts]:
        artifacts.append(_artifact_summary(root, raw_path, max_input_bytes=max_input_bytes, blockers=blockers))
    body = {
        "schemaVersion": DIAGNOSTIC_BUNDLE_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "projectRoot": "<checkout>",
        "sourceOfTruth": False,
        "redacted": True,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
        "resourceCaps": {
            "maxArtifacts": max_artifacts,
            "maxInputBytes": max_input_bytes,
        },
        "artifactCount": len(artifacts),
        "artifacts": artifacts,
        "blockers": blockers,
    }
    rendered = json.dumps(body, ensure_ascii=False, sort_keys=True)
    if str(root) in rendered:
        blockers.append({"code": "diagnostic-bundle-redaction-failed", "message": "project root leaked into bundle"})
        body["status"] = "FAIL"
        body["blockers"] = blockers
    return {**body, "bundleDigest": canonical_digest(body)}


def require_diagnostic_bundle_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("diagnostic-bundle-validation-failed", "diagnostic bundle validation failed", {"validation": payload})
    return payload


def _artifact_summary(root: Path, raw_path: Path, *, max_input_bytes: int, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    path = _resolve(root, raw_path)
    display_path = _display_path(path, root)
    if not path.is_file():
        blockers.append({"code": "diagnostic-bundle-artifact-missing", "path": display_path})
        return {"path": display_path, "status": "MISSING", "identity": None, "summary": {}}
    data = path.read_bytes()
    identity = {"path": display_path, "sha256": sha256_hex(data), "bytes": len(data)}
    if len(data) > max_input_bytes:
        blockers.append({"code": "diagnostic-bundle-artifact-too-large", "path": display_path, "bytes": len(data), "maxInputBytes": max_input_bytes})
        return {"path": display_path, "status": "TOO_LARGE", "identity": identity, "summary": {}}
    try:
        payload = load_json_object(data, label=display_path)
    except LifecycleError as error:
        blockers.append({"code": error.code, "path": display_path, "message": error.message})
        return {"path": display_path, "status": "INVALID", "identity": identity, "summary": {}}
    redacted = _redact(payload, root)
    return {
        "path": display_path,
        "status": "PASS",
        "identity": identity,
        "schemaVersion": payload.get("schemaVersion"),
        "artifactStatus": payload.get("status"),
        "summary": {
            "topLevelKeys": sorted(payload.keys()),
            "blockerCount": len(payload.get("blockers", [])) if isinstance(payload.get("blockers"), list) else 0,
            "productionPromotionClaimed": payload.get("productionPromotionClaimed") is True,
            "redactedDigest": canonical_digest(redacted),
        },
    }


def _redact(value: Any, root: Path) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = _redact(item, root)
        return result
    if isinstance(value, list):
        return [_redact(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), "<checkout>")
    return value


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name
