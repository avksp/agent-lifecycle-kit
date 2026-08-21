"""Contained local storage and bounded restoration for context checkpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.canonical import (
    canonical_bytes,
    ensure_private_directory,
    require_private_file,
    write_json_replace_private,
)
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.context.checkpoints import (
    CHECKPOINT_SCHEMA,
    DEFAULT_MAX_CHECKPOINT_BYTES,
    DEFAULT_TARGET_TOKENS,
    require_context_checkpoint_pass,
    validate_context_checkpoint,
)

DEFAULT_CHECKPOINT_ROOT = Path(".alk/context/checkpoints")
MAX_CHECKPOINTS_PER_RUN = 64


def checkpoint_path(checkpoint_id: str, *, root: Path | None = None) -> Path:
    """Return a path contained by the configured checkpoint directory."""

    if not isinstance(checkpoint_id, str) or not checkpoint_id or checkpoint_id in {".", ".."}:
        raise LifecycleError("context-checkpoint-id-invalid", "checkpoint id is required")
    if "/" in checkpoint_id or "\\" in checkpoint_id or "\x00" in checkpoint_id:
        raise LifecycleError("context-checkpoint-id-invalid", "checkpoint id must be a single path component")
    directory = root or DEFAULT_CHECKPOINT_ROOT
    path = directory / f"{checkpoint_id}.json"
    if not path.resolve().is_relative_to(directory.resolve()):
        raise LifecycleError("context-checkpoint-path-escape", "checkpoint path escapes the checkpoint root")
    return path


def write_context_checkpoint(
    checkpoint: dict[str, Any],
    *,
    root: Path | None = None,
    max_checkpoints_per_run: int = MAX_CHECKPOINTS_PER_RUN,
) -> dict[str, Any]:
    """Write a checkpoint once and retain only the latest bounded set per run."""

    validation = validate_context_checkpoint(checkpoint)
    require_context_checkpoint_pass(validation)
    path = checkpoint_path(str(checkpoint["checkpointId"]), root=root)
    ensure_private_directory(path.parent)
    created = not path.exists()
    if not created:
        require_private_file(path)
        existing = read_json_object(path, label="existing context checkpoint")
        if canonical_digest(existing) != canonical_digest(checkpoint):
            raise LifecycleError("context-checkpoint-conflict", "checkpoint id already contains a different artifact")
    else:
        write_json_replace_private(path, checkpoint)
    _retain_latest(path.parent, run_id=str(checkpoint["runId"]), limit=max_checkpoints_per_run)
    return {
        "status": "PASS",
        "path": path.as_posix(),
        "checkpointId": checkpoint["checkpointId"],
        "checkpointDigest": checkpoint["checkpointDigest"],
        "created": created,
        "retentionPolicy": "retain-latest-with-explicit-delete",
        "maxCheckpointsPerRun": max_checkpoints_per_run,
        "productionPromotionClaimed": False,
    }


def load_context_checkpoint(checkpoint_id: str, *, root: Path | None = None) -> dict[str, Any]:
    path = checkpoint_path(checkpoint_id, root=root)
    require_private_file(path)
    return read_json_object(path, label="context checkpoint")


def list_context_checkpoints(*, root: Path | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    directory = (root or DEFAULT_CHECKPOINT_ROOT).resolve()
    if not directory.exists():
        return []
    ensure_private_directory(directory)
    if not directory.is_dir():
        raise LifecycleError("context-checkpoint-root-invalid", "checkpoint root is not a directory")
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if not path.resolve().is_relative_to(directory):
            raise LifecycleError("context-checkpoint-path-escape", "checkpoint listing escaped the checkpoint root")
        require_private_file(path)
        value = read_json_object(path, label="context checkpoint")
        if run_id is None or value.get("runId") == run_id:
            result.append(value)
    return sorted(result, key=lambda item: (str(item.get("createdAt", "")), str(item.get("checkpointId", ""))))


def restore_context_checkpoint(
    checkpoint_path_value: Path,
    *,
    state: dict[str, Any],
    session_id: str | None = None,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_checkpoint_bytes: int = DEFAULT_MAX_CHECKPOINT_BYTES,
) -> dict[str, Any]:
    """Return a bounded continuation packet after checking current lineage."""

    require_private_file(checkpoint_path_value)
    checkpoint = read_json_object(checkpoint_path_value, label="context checkpoint")
    expected = _lineage_from_state(state, session_id=session_id)
    validation = validate_context_checkpoint(
        checkpoint,
        expected_lineage=expected,
        max_checkpoint_bytes=max_checkpoint_bytes,
        target_tokens=target_tokens,
    )
    if validation["status"] == "FAIL":
        return {
            "schemaVersion": "agent-context-continuation.v1",
            "status": "BLOCKED",
            "checkpointId": checkpoint.get("checkpointId"),
            "validation": validation,
            "implementationAuthorized": False,
            "proofAuthority": "none",
            "productionPromotionClaimed": False,
        }
    summary, redaction_applied = redact_value(checkpoint["summary"])
    if redaction_applied:
        return {
            "schemaVersion": "agent-context-continuation.v1",
            "status": "BLOCKED",
            "checkpointId": checkpoint.get("checkpointId"),
            "validation": {
                **validation,
                "status": "FAIL",
                "blockers": [{"code": "context-restore-unredacted-sensitive-input"}],
            },
            "implementationAuthorized": False,
            "proofAuthority": "none",
            "productionPromotionClaimed": False,
        }
    continuation = {
        "schemaVersion": "agent-context-continuation.v1",
        "status": "PASS",
        "checkpointId": checkpoint["checkpointId"],
        "checkpointDigest": checkpoint["checkpointDigest"],
        "lineage": {
            key: checkpoint[key]
            for key in ("sessionId", "runId", "adapterId", "packageId", "planRevision", "planDigest", "stateRevision", "sourceRevision")
        },
        "captureMode": checkpoint["captureMode"],
        "summary": summary,
        "referencedArtifacts": checkpoint["referencedArtifacts"],
        "implementationAuthorized": False,
        "proofAuthority": "none",
        "contextLimits": {"targetTokens": target_tokens, "maxBytes": max_checkpoint_bytes},
        "validationDigest": validation["validationDigest"],
        "productionPromotionClaimed": False,
    }
    continuation["continuationDigest"] = canonical_digest(continuation)
    if (len(canonical_bytes(continuation)) + 3) // 4 > target_tokens * 2:
        return {
            "schemaVersion": "agent-context-continuation.v1",
            "status": "BLOCKED",
            "checkpointId": checkpoint.get("checkpointId"),
            "validation": {
                **validation,
                "status": "FAIL",
                "blockers": [{"code": "context-restore-token-limit"}],
            },
            "implementationAuthorized": False,
            "proofAuthority": "none",
            "productionPromotionClaimed": False,
        }
    return continuation


def _lineage_from_state(state: dict[str, Any], *, session_id: str | None) -> dict[str, Any]:
    fields = ("runId", "packageId", "planRevision", "planDigest", "stateRevision", "sourceRevision")
    expected = {key: state.get(key) for key in fields if key in state}
    if session_id is not None:
        expected["sessionId"] = session_id
    return expected


def _retain_latest(directory: Path, *, run_id: str, limit: int) -> None:
    if not isinstance(limit, int) or limit < 1 or limit > MAX_CHECKPOINTS_PER_RUN:
        raise LifecycleError("context-checkpoint-retention-invalid", "retention limit must be between 1 and 64")
    items = list_context_checkpoints(root=directory, run_id=run_id)
    for item in items[:-limit]:
        path = checkpoint_path(str(item["checkpointId"]), root=directory)
        if path.resolve().is_relative_to(directory.resolve()):
            path.unlink()
