"""Bounded conversion of pre-2.0 runner artifacts.

The converter is deliberately not a workflow adapter.  It validates one
explicit input, records only bounded historical facts, and writes a private
archival record without changing the source or any workflow state.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.contracts.canonical import write_json_create_private
from agent_lifecycle.contracts.legacy_runner_schemas import LEGACY_RUNNER_SCHEMAS
from agent_lifecycle.contracts.redaction import redact_value

CONVERSION_SCHEMA = "agent-workflow-legacy-runner-conversion.v1"
CONVERSION_VERSION = "2.0.0"
LEGACY_ARTIFACT_MAX_BYTES = 1_048_576
_DIGEST_FIELDS = ("stateDigest", "resultDigest", "snapshotDigest", "validationDigest", "receiptDigest", "actionDigest")
_SELF_DIGEST_FIELDS = {
    "agent-managed-lifecycle-next-action.v1": "actionDigest",
    "agent-managed-lifecycle-runner-receipt.v1": "receiptDigest",
    "agent-runner-state.v1": "stateDigest",
    "agent-runner-transition-result.v1": "resultDigest",
    "agent-runner-snapshot.v1": "snapshotDigest",
    "agent-runner-attempt-snapshot-receipt.v1": "receiptDigest",
    "agent-runner-attempt-snapshot-receipt-validation.v1": "validationDigest",
}
_LINEAGE_FIELDS = (
    "runId",
    "packageId",
    "planRevision",
    "planDigest",
    "taskId",
    "sourceRevision",
    "runnerRevision",
)
_FACT_FIELDS = (
    "status",
    "runnerStatus",
    "currentTaskId",
    "runnerRevision",
    "attempt",
    "estimatedTokens",
    "historyCount",
)
_MAX_FACT_ITEMS = 32
_MAX_UNMAPPED_FIELDS = 64


def convert_legacy_runner_artifact(
    input_path: Path,
    output_path: Path,
    *,
    expected_sha256: str | None = None,
    max_input_bytes: int = LEGACY_ARTIFACT_MAX_BYTES,
) -> dict[str, Any]:
    """Convert one supported legacy artifact into a non-authoritative record."""

    _validate_input_cap(max_input_bytes)
    if expected_sha256 is not None:
        _validate_digest(expected_sha256, code="invalid-expected-artifact-digest")
    raw = _read_stable_input(input_path, max_bytes=max_input_bytes)
    source_sha256 = sha256_hex(raw)
    if expected_sha256 is not None and source_sha256 != expected_sha256:
        raise LifecycleError(
            "legacy-artifact-digest-mismatch",
            "legacy artifact SHA-256 does not match the expected digest",
            {"expectedSha256": expected_sha256, "actualSha256": source_sha256},
        )
    payload = load_json_object(raw, label="legacy runner artifact")
    schema_id = payload.get("schemaVersion")
    if schema_id not in LEGACY_RUNNER_SCHEMAS:
        raise LifecycleError(
            "legacy-artifact-schema-unsupported",
            "legacy artifact schema is not supported for conversion",
            {"schemaVersion": schema_id},
        )
    _validate_legacy_payload(payload, schema_id)
    _validate_embedded_digests(payload, schema_id=schema_id)
    record = _build_conversion_record(payload, schema_id=schema_id, source_sha256=source_sha256, source_bytes=len(raw))
    _prepare_output_path(output_path)
    try:
        write_json_create_private(output_path, record)
    except FileExistsError as exc:
        raise LifecycleError("legacy-conversion-output-exists", "conversion output already exists") from exc
    return record


def _build_conversion_record(
    payload: dict[str, Any],
    *,
    schema_id: str,
    source_sha256: str,
    source_bytes: int,
) -> dict[str, Any]:
    lineage: dict[str, Any] = {}
    for field in _LINEAGE_FIELDS:
        if field in payload:
            lineage[field] = _bounded_value(payload[field])
    nested_lineage = payload.get("lineage")
    if isinstance(nested_lineage, dict):
        for field in _LINEAGE_FIELDS:
            if field not in lineage and field in nested_lineage:
                lineage[field] = _bounded_value(nested_lineage[field])

    facts: dict[str, Any] = {}
    for field in _FACT_FIELDS:
        if field in payload:
            facts[field] = _bounded_value(payload[field])
    history = payload.get("history")
    if isinstance(history, list):
        facts["historyCount"] = len(history)
    operations = payload.get("operations")
    if isinstance(operations, dict):
        facts["operationCount"] = len(operations)
    counters = payload.get("counters")
    if isinstance(counters, dict):
        facts["counterKeys"] = sorted(str(key) for key in counters)[:_MAX_FACT_ITEMS]

    known_fields = {
        "schemaVersion",
        *_LINEAGE_FIELDS,
        *_FACT_FIELDS,
        *_DIGEST_FIELDS,
        "lineage",
        "history",
        "operations",
        "counters",
        "status",
        "state",
        "plan",
        "nextAction",
        "blockers",
        "authority",
        "deprecation",
        "policy",
        "runner",
        "budget",
        "recentTransitions",
        "snapshot",
        "metadata",
        "createdAt",
        "reason",
        "action",
        "transition",
        "allowedNextActions",
        "taskId",
        "attempt",
        "selectedAttempt",
        "selectedAttemptDigest",
        "restoreSourceDigest",
        "abandonReason",
        "evidenceIds",
        "productionPromotionClaimed",
        "modelCallsStarted",
        "stateWritten",
        "hostLaunchStarted",
    }
    unmapped_fields = sorted(str(key) for key in payload if key not in known_fields)[:_MAX_UNMAPPED_FIELDS]
    warnings = []
    if unmapped_fields:
        warnings.append({"code": "legacy-fields-not-mapped", "fields": unmapped_fields})
    body: dict[str, Any] = {
        "schemaVersion": CONVERSION_SCHEMA,
        "status": "PASS",
        "conversionStatus": "CONVERTED",
        "conversionVersion": CONVERSION_VERSION,
        "source": {
            "schemaVersion": schema_id,
            "sha256": source_sha256,
            "bytes": source_bytes,
        },
        "lineage": lineage,
        "facts": facts,
        "unmappedFields": unmapped_fields,
        "warnings": warnings,
        "blockers": [],
        "authorityClaimed": False,
        "stateWritten": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "conversionDigest": canonical_digest(body)}


def _validate_legacy_payload(payload: dict[str, Any], schema_id: str) -> None:
    schema = LEGACY_RUNNER_SCHEMAS[schema_id]
    required = schema.get("required", [])
    missing = [field for field in required if field not in payload]
    if missing:
        raise LifecycleError(
            "legacy-artifact-schema-invalid",
            "legacy artifact is missing required fields",
            {"schemaVersion": schema_id, "missing": missing},
        )
    properties = schema.get("properties", {})
    for field, rule in properties.items():
        if field not in payload or not isinstance(rule, dict):
            continue
        value = payload[field]
        if "const" in rule and value != rule["const"]:
            raise LifecycleError(
                "legacy-artifact-schema-invalid",
                "legacy artifact contains a forbidden contract value",
                {"schemaVersion": schema_id, "field": field},
            )
        if "enum" in rule and value not in rule["enum"]:
            raise LifecycleError(
                "legacy-artifact-schema-invalid",
                "legacy artifact contains an unsupported contract value",
                {"schemaVersion": schema_id, "field": field},
            )
        if not _matches_type(value, rule.get("type")):
            raise LifecycleError(
                "legacy-artifact-schema-invalid",
                "legacy artifact field has the wrong type",
                {"schemaVersion": schema_id, "field": field},
            )
        if isinstance(value, str) and "minLength" in rule and len(value) < int(rule["minLength"]):
            raise LifecycleError(
                "legacy-artifact-schema-invalid",
                "legacy artifact field is empty",
                {"schemaVersion": schema_id, "field": field},
            )
        if isinstance(value, str) and "maxLength" in rule and len(value) > int(rule["maxLength"]):
            raise LifecycleError(
                "legacy-artifact-schema-invalid",
                "legacy artifact field exceeds its contract limit",
                {"schemaVersion": schema_id, "field": field},
            )
        if isinstance(value, int) and not isinstance(value, bool) and "minimum" in rule and value < int(rule["minimum"]):
            raise LifecycleError(
                "legacy-artifact-schema-invalid",
                "legacy artifact integer is below its contract limit",
                {"schemaVersion": schema_id, "field": field},
            )


def _validate_embedded_digests(payload: dict[str, Any], *, schema_id: str) -> None:
    for field in _DIGEST_FIELDS:
        value = payload.get(field)
        if value is None:
            continue
        _validate_digest(value, code="legacy-artifact-digest-invalid")
    self_digest_field = _SELF_DIGEST_FIELDS.get(schema_id)
    if self_digest_field is not None and self_digest_field in payload:
        value = payload[self_digest_field]
        expected = canonical_digest({key: item for key, item in payload.items() if key != self_digest_field})
        if value != expected:
            raise LifecycleError(
                "legacy-artifact-digest-mismatch",
                "legacy artifact contains a stale embedded digest",
                {"field": self_digest_field},
            )
    if schema_id == "agent-runner-attempt-snapshot-receipt.v1":
        snapshot = payload.get("snapshot")
        snapshot_digest = payload.get("snapshotDigest")
        if isinstance(snapshot, dict) and snapshot_digest is not None and snapshot_digest != canonical_digest(snapshot):
            raise LifecycleError(
                "legacy-artifact-digest-mismatch",
                "legacy artifact contains a stale snapshot digest",
                {"field": "snapshotDigest"},
            )


def _matches_type(value: Any, type_spec: Any) -> bool:
    if type_spec is None:
        return True
    allowed = type_spec if isinstance(type_spec, list) else [type_spec]
    for expected in allowed:
        if expected == "null" and value is None:
            return True
        if expected == "object" and isinstance(value, dict):
            return True
        if expected == "array" and isinstance(value, list):
            return True
        if expected == "string" and isinstance(value, str):
            return True
        if expected == "boolean" and isinstance(value, bool):
            return True
        if expected == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
    return False


def _bounded_value(value: Any) -> Any:
    redacted, _changed = redact_value(value)
    if isinstance(redacted, str):
        return redacted[:256]
    if isinstance(redacted, (int, float, bool)) or redacted is None:
        return redacted
    if isinstance(redacted, list):
        return [_bounded_value(item) for item in redacted[:_MAX_FACT_ITEMS]]
    if isinstance(redacted, dict):
        return {str(key)[:128]: _bounded_value(item) for key, item in list(redacted.items())[:_MAX_FACT_ITEMS]}
    return str(redacted)[:256]


def _read_stable_input(path: Path, *, max_bytes: int) -> bytes:
    absolute = path.absolute()
    _reject_symlink_components(absolute)
    try:
        before_path = os.stat(absolute, follow_symlinks=False)
    except OSError as exc:
        raise LifecycleError("legacy-artifact-unavailable", "legacy artifact is unavailable") from exc
    if not stat.S_ISREG(before_path.st_mode):
        raise LifecycleError("legacy-artifact-not-regular", "legacy artifact must be a regular file")
    if before_path.st_size > max_bytes:
        raise LifecycleError("legacy-artifact-too-large", "legacy artifact exceeds the configured byte limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(os.fspath(absolute), flags)
    except OSError as exc:
        raise LifecycleError("legacy-artifact-open-failed", "legacy artifact could not be opened safely") from exc
    try:
        with os.fdopen(fd, "rb", closefd=True) as handle:
            before_fd = os.fstat(handle.fileno())
            _require_same_file(before_path, before_fd)
            data = handle.read(max_bytes + 1)
            after_fd = os.fstat(handle.fileno())
            _require_same_file(before_fd, after_fd)
    except LifecycleError:
        raise
    except OSError as exc:
        raise LifecycleError("legacy-artifact-read-failed", "legacy artifact could not be read safely") from exc
    if len(data) > max_bytes:
        raise LifecycleError("legacy-artifact-too-large", "legacy artifact exceeds the configured byte limit")
    try:
        after_path = os.stat(absolute, follow_symlinks=False)
    except OSError as exc:
        raise LifecycleError("legacy-artifact-changed-during-read", "legacy artifact changed during read") from exc
    _require_same_file(before_path, after_path)
    return data


def _require_same_file(before: os.stat_result, after: os.stat_result) -> None:
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if os.name != "nt":
        fields += ("st_ctime_ns",)
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise LifecycleError("legacy-artifact-changed-during-read", "legacy artifact changed during read")


def _reject_symlink_components(path: Path) -> None:
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise LifecycleError("legacy-artifact-symlink", "legacy artifact path must not contain symlinks")
        current = current.parent


def _prepare_output_path(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise LifecycleError("legacy-conversion-output-symlink", "conversion output must not be a symlink")
    _reject_output_symlink_components(path.absolute().parent)


def _reject_output_symlink_components(path: Path) -> None:
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise LifecycleError("legacy-conversion-output-symlink", "conversion output path must not contain symlinks")
        current = current.parent


def _validate_input_cap(max_input_bytes: int) -> None:
    if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes <= 0:
        raise LifecycleError("invalid-legacy-artifact-cap", "max-input-bytes must be a positive integer")
    if max_input_bytes > LEGACY_ARTIFACT_MAX_BYTES:
        raise LifecycleError(
            "invalid-legacy-artifact-cap",
            "max-input-bytes exceeds the hard legacy artifact limit",
            {"maxBytes": LEGACY_ARTIFACT_MAX_BYTES},
        )


def _validate_digest(value: Any, *, code: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleError(code, "artifact digest must be a 64-character hexadecimal SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise LifecycleError(code, "artifact digest must be hexadecimal") from exc


__all__ = [
    "CONVERSION_SCHEMA",
    "LEGACY_ARTIFACT_MAX_BYTES",
    "convert_legacy_runner_artifact",
]
