"""Deterministic, bounded context checkpoint contracts and validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.context_checkpoint_schemas import CHECKPOINT_MODES
from agent_lifecycle.contracts.redaction import contains_local_absolute_path, redact_value

CHECKPOINT_SCHEMA = "agent-context-checkpoint.v1"
VALIDATION_SCHEMA = "agent-context-checkpoint-validation.v1"
EVENT_SCHEMA = "agent-context-checkpoint-event.v1"
DEFAULT_MAX_CHECKPOINT_BYTES = 131_072
DEFAULT_MAX_CHECKPOINT_REFERENCES = 32
DEFAULT_TARGET_TOKENS = 2_048

_MAX_SUMMARY_ITEMS = 32
_MAX_SUMMARY_STRING = 4_096
_FORBIDDEN_KEYS = {
    "rawTranscript",
    "transcript",
    "conversation",
    "messages",
    "chatHistory",
    "systemPrompt",
    "developerPrompt",
    "prompt",
    "promptAuthority",
    "toolAuthority",
    "freezeAuthority",
    "acceptanceAuthority",
    "implementationAuthority",
    "implementationAuthorized",
    "proofAuthority",
}
def build_context_checkpoint(
    *,
    session_id: str,
    run_id: str,
    adapter_id: str,
    package_id: str,
    plan_revision: int,
    plan_digest: str,
    state_revision: int,
    source_revision: str,
    capture_mode: str,
    reason: str,
    summary: dict[str, Any],
    referenced_artifacts: list[dict[str, Any]] | None = None,
    capture_evidence: dict[str, Any] | None = None,
    created_at: str = "1970-01-01T00:00:00Z",
    checkpoint_id: str | None = None,
    max_checkpoint_bytes: int = DEFAULT_MAX_CHECKPOINT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    """Build a redacted checkpoint from structured local input only.

    The default timestamp keeps the pure builder deterministic. Runtime callers
    should pass their event timestamp explicitly.
    """

    _require_text_fields(
        {
            "sessionId": session_id,
            "runId": run_id,
            "adapterId": adapter_id,
            "packageId": package_id,
            "planDigest": plan_digest,
            "sourceRevision": source_revision,
            "reason": reason,
            "createdAt": created_at,
        }
    )
    _require_positive_int(plan_revision, "planRevision")
    _require_positive_int(state_revision, "stateRevision")
    _require_digest(plan_digest, "planDigest")
    if capture_mode not in CHECKPOINT_MODES:
        raise LifecycleError("context-checkpoint-mode-invalid", "unsupported context checkpoint capture mode")
    if not isinstance(summary, dict):
        raise LifecycleError("context-checkpoint-summary-invalid", "checkpoint summary must be an object")
    if not isinstance(referenced_artifacts, list):
        referenced_artifacts = []
    if len(referenced_artifacts) > DEFAULT_MAX_CHECKPOINT_REFERENCES:
        raise LifecycleError("context-checkpoint-references-exceeded", "checkpoint references exceed the configured cap")
    _reject_authority_fields(summary)
    safe_summary, redaction_applied = redact_value(summary)
    _validate_bounded_value(safe_summary, label="summary")
    safe_artifacts, artifacts_redacted = redact_value(referenced_artifacts)
    _validate_artifacts(safe_artifacts)
    safe_capture_evidence = _normalize_capture_evidence(capture_mode, capture_evidence)
    redaction_applied = redaction_applied or artifacts_redacted
    body: dict[str, Any] = {
        "schemaVersion": CHECKPOINT_SCHEMA,
        "status": "PASS",
        "checkpointId": checkpoint_id or _checkpoint_id(
            session_id=session_id,
            state_revision=state_revision,
            capture_mode=capture_mode,
            summary=safe_summary,
            capture_evidence=safe_capture_evidence,
        ),
        "sessionId": session_id,
        "runId": run_id,
        "adapterId": adapter_id,
        "packageId": package_id,
        "planRevision": plan_revision,
        "planDigest": plan_digest,
        "stateRevision": state_revision,
        "sourceRevision": source_revision,
        "captureMode": capture_mode,
        "supportLevel": capture_mode,
        "reason": reason,
        "summary": safe_summary,
        "referencedArtifacts": safe_artifacts,
        "captureEvidence": safe_capture_evidence,
        "redactionStatus": {
            "checked": True,
            "applied": redaction_applied,
            "policy": "shared-contract-redaction-v1",
        },
        "implementationAuthorized": False,
        "proofAuthority": "none",
        "createdAt": created_at,
        "productionPromotionClaimed": False,
    }
    body["checkpointDigest"] = canonical_digest(body)
    _enforce_checkpoint_limits(body, max_checkpoint_bytes=max_checkpoint_bytes, target_tokens=target_tokens)
    return body


def validate_context_checkpoint(
    checkpoint: dict[str, Any],
    *,
    expected_lineage: dict[str, Any] | None = None,
    max_checkpoint_bytes: int = DEFAULT_MAX_CHECKPOINT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> dict[str, Any]:
    """Validate shape, authority, redaction, digest and optional lineage."""

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    if not isinstance(checkpoint, dict):
        blockers.append({"code": "context-checkpoint-object-required"})
        return _validation(None, checks, blockers)
    checkpoint_id = checkpoint.get("checkpointId")
    required = (
        "schemaVersion", "status", "checkpointId", "sessionId", "runId", "adapterId", "packageId",
        "planRevision", "planDigest", "stateRevision", "sourceRevision", "captureMode", "supportLevel",
        "reason", "summary", "referencedArtifacts", "captureEvidence", "redactionStatus", "implementationAuthorized",
        "proofAuthority", "createdAt", "productionPromotionClaimed", "checkpointDigest",
    )
    missing = [key for key in required if key not in checkpoint]
    if missing:
        blockers.append({"code": "context-checkpoint-fields-missing", "fields": missing})
    if checkpoint.get("schemaVersion") != CHECKPOINT_SCHEMA:
        blockers.append({"code": "context-checkpoint-schema-invalid"})
    if checkpoint.get("status") != "PASS":
        blockers.append({"code": "context-checkpoint-status-invalid"})
    if checkpoint.get("captureMode") not in CHECKPOINT_MODES or checkpoint.get("supportLevel") != checkpoint.get("captureMode"):
        blockers.append({"code": "context-checkpoint-mode-invalid"})
    if checkpoint.get("implementationAuthorized") is not False or checkpoint.get("proofAuthority") != "none":
        blockers.append({"code": "context-checkpoint-authority-present"})
    if checkpoint.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "context-checkpoint-production-claim"})
    try:
        _normalize_capture_evidence(checkpoint.get("captureMode"), checkpoint.get("captureEvidence"))
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message})
    summary = checkpoint.get("summary")
    if not isinstance(summary, dict):
        blockers.append({"code": "context-checkpoint-summary-invalid"})
    else:
        try:
            _reject_authority_fields(summary)
            redacted, changed = redact_value(summary)
            if changed and redacted != summary:
                blockers.append({"code": "context-checkpoint-unredacted-sensitive-input"})
            _validate_bounded_value(summary, label="summary")
        except LifecycleError as exc:
            blockers.append({"code": exc.code, "message": exc.message})
    try:
        _validate_artifacts(checkpoint.get("referencedArtifacts"))
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message})
    expected_digest = canonical_digest({key: value for key, value in checkpoint.items() if key != "checkpointDigest"})
    if checkpoint.get("checkpointDigest") != expected_digest:
        blockers.append({"code": "context-checkpoint-digest-mismatch"})
    try:
        _enforce_checkpoint_limits(checkpoint, max_checkpoint_bytes=max_checkpoint_bytes, target_tokens=target_tokens)
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message})
    if expected_lineage:
        fields = (
            "sessionId", "runId", "packageId", "planRevision", "planDigest", "stateRevision", "sourceRevision",
        )
        mismatch = {
            key: {"expected": expected_lineage.get(key), "actual": checkpoint.get(key)}
            for key in fields
            if key in expected_lineage and expected_lineage.get(key) != checkpoint.get(key)
        }
        if mismatch:
            blockers.append({"code": "context-checkpoint-lineage-mismatch", "fields": mismatch})
    checks.extend(
        [
            {"id": "schema", "status": "PASS" if checkpoint.get("schemaVersion") == CHECKPOINT_SCHEMA else "FAIL"},
            {"id": "authority", "status": "PASS" if checkpoint.get("proofAuthority") == "none" else "FAIL"},
            {"id": "digest", "status": "PASS" if checkpoint.get("checkpointDigest") == expected_digest else "FAIL"},
            {"id": "lineage", "status": "PASS" if not any(item.get("code") == "context-checkpoint-lineage-mismatch" for item in blockers) else "FAIL"},
        ]
    )
    return _validation(checkpoint_id if isinstance(checkpoint_id, str) else None, checks, blockers)


def require_context_checkpoint_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") == "FAIL":
        raise LifecycleError("context-checkpoint-validation-failed", "context checkpoint validation failed", {"validation": validation})
    return validation


def _validation(checkpoint_id: str | None, checks: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "checkpointId": checkpoint_id,
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _checkpoint_id(
    *,
    session_id: str,
    state_revision: int,
    capture_mode: str,
    summary: dict[str, Any],
    capture_evidence: dict[str, Any] | None,
) -> str:
    digest = canonical_digest(
        {
            "sessionId": session_id,
            "stateRevision": state_revision,
            "captureMode": capture_mode,
            "summary": summary,
            "captureEvidence": capture_evidence,
        }
    )
    return f"ctx-{digest[:24]}"


def validate_native_hook_evidence(value: Any) -> dict[str, Any]:
    """Validate the adapter-owned proof required for a native hook claim."""

    if not isinstance(value, dict):
        raise LifecycleError(
            "context-checkpoint-native-hook-evidence-required",
            "NATIVE_HOOK requires adapter-owned capture evidence",
        )
    safe_value, changed = redact_value(value)
    if changed or safe_value != value:
        raise LifecycleError(
            "context-checkpoint-native-hook-evidence-unredacted",
            "native hook evidence must not contain redacted values",
        )
    if safe_value.get("status") != "PASS" or safe_value.get("accepted") is not True:
        raise LifecycleError(
            "context-checkpoint-native-hook-evidence-invalid",
            "native hook evidence must be accepted with PASS status",
        )
    if safe_value.get("producerBoundary") != "adapter-owned":
        raise LifecycleError(
            "context-checkpoint-native-hook-producer-invalid",
            "native hook evidence must identify an adapter-owned producer",
        )
    for key in ("capabilityReceiptDigest", "eventReceiptDigest"):
        digest = safe_value.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise LifecycleError(
                "context-checkpoint-native-hook-evidence-digest-invalid",
                f"native hook evidence requires a valid {key}",
            )
    _validate_bounded_value(safe_value, label="captureEvidence")
    return safe_value


def _normalize_capture_evidence(capture_mode: str | None, value: Any) -> dict[str, Any] | None:
    if capture_mode == "NATIVE_HOOK":
        return validate_native_hook_evidence(value)
    if value is not None:
        raise LifecycleError(
            "context-checkpoint-evidence-unexpected",
            "capture evidence is only allowed for NATIVE_HOOK checkpoints",
        )
    return None


def _require_text_fields(fields: dict[str, Any]) -> None:
    for name, value in fields.items():
        if not isinstance(value, str) or not value:
            raise LifecycleError("context-checkpoint-field-invalid", f"{name} must be a non-empty string")


def _require_positive_int(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError("context-checkpoint-field-invalid", f"{name} must be a positive integer")


def _require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise LifecycleError("context-checkpoint-digest-invalid", f"{name} must be a lowercase SHA-256 digest")


def _reject_authority_fields(value: Any, *, path: str = "summary") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key in _FORBIDDEN_KEYS:
                raise LifecycleError("context-checkpoint-authority-field", f"{path}.{key} is not allowed in a checkpoint summary")
            _reject_authority_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_authority_fields(child, path=f"{path}[{index}]")
    # Private paths are redacted at the boundary. They are rejected later if a
    # caller presents an already-built artifact that still contains one.


def _validate_bounded_value(value: Any, *, label: str, depth: int = 0) -> None:
    if depth > 8:
        raise LifecycleError("context-checkpoint-depth-exceeded", f"{label} nesting exceeds the limit")
    if isinstance(value, str):
        if len(value) > _MAX_SUMMARY_STRING:
            raise LifecycleError("context-checkpoint-string-exceeded", f"{label} contains an oversized string")
        if contains_local_absolute_path(value):
            raise LifecycleError("context-checkpoint-private-path", f"{label} contains a private absolute path")
        return
    if isinstance(value, dict):
        if len(value) > _MAX_SUMMARY_ITEMS:
            raise LifecycleError("context-checkpoint-fields-exceeded", f"{label} contains too many fields")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise LifecycleError("context-checkpoint-key-invalid", f"{label} contains an invalid key")
            _validate_bounded_value(child, label=f"{label}.{key}", depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > _MAX_SUMMARY_ITEMS:
            raise LifecycleError("context-checkpoint-items-exceeded", f"{label} contains too many items")
        for index, child in enumerate(value):
            _validate_bounded_value(child, label=f"{label}[{index}]", depth=depth + 1)
        return
    if value is not None and not isinstance(value, (bool, int, float)):
        raise LifecycleError("context-checkpoint-value-invalid", f"{label} contains a non-JSON value")


def _validate_artifacts(artifacts: Any) -> None:
    if not isinstance(artifacts, list) or len(artifacts) > DEFAULT_MAX_CHECKPOINT_REFERENCES:
        raise LifecycleError("context-checkpoint-references-invalid", "referencedArtifacts must be a bounded array")
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise LifecycleError("context-checkpoint-artifact-invalid", f"referencedArtifacts[{index}] must be an object")
        if "path" in artifact and isinstance(artifact["path"], str) and artifact["path"].startswith("/"):
            raise LifecycleError("context-checkpoint-private-path", "referenced artifact paths must be repository-relative")
        if "digest" in artifact:
            _require_digest(artifact["digest"], f"referencedArtifacts[{index}].digest")
        _validate_bounded_value(artifact, label=f"referencedArtifacts[{index}]")


def _enforce_checkpoint_limits(checkpoint: dict[str, Any], *, max_checkpoint_bytes: int, target_tokens: int) -> None:
    if not isinstance(max_checkpoint_bytes, int) or max_checkpoint_bytes < 1:
        raise LifecycleError("context-checkpoint-limit-invalid", "max checkpoint bytes must be positive")
    if not isinstance(target_tokens, int) or target_tokens < 1:
        raise LifecycleError("context-checkpoint-limit-invalid", "target continuation tokens must be positive")
    byte_count = len(canonical_bytes(checkpoint))
    if byte_count > max_checkpoint_bytes:
        raise LifecycleError("context-checkpoint-bytes-exceeded", "checkpoint exceeds the byte limit", {"bytes": byte_count, "limit": max_checkpoint_bytes})
    estimated_tokens = (byte_count + 3) // 4
    if estimated_tokens > target_tokens * 2:
        raise LifecycleError("context-checkpoint-tokens-exceeded", "checkpoint exceeds the continuation token budget", {"estimatedTokens": estimated_tokens, "limit": target_tokens * 2})
