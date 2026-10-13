"""Closed pure D-DEADLINE records; native clock and producer trust are separate."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError

_MAX = (1 << 63) - 1
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
CLOCK_OBSERVATION_V1 = "agent-workflow-clock-observation.v1"
PERMISSION_RULE_V1 = "agent-closing-permission-rule.v1"
DURATION_RULE_V1 = "agent-closing-duration-rule.v1"
FRESHNESS_RULE_V1 = "agent-closing-freshness-rule.v1"
FIXED_DEADLINE_RULE_V1 = "agent-closing-fixed-deadline-rule.v1"
_TEXT = {"type": "string", "minLength": 1, "maxLength": 256}
_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_UTC = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"}
_UINT = {"type": "integer", "minimum": 0, "maximum": _MAX}


def _schema(schema_id: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": schema_id,
            "type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


DEADLINE_SCHEMAS = {
    CLOCK_OBSERVATION_V1: _schema(CLOCK_OBSERVATION_V1, {
        "schemaVersion": {"const": CLOCK_OBSERVATION_V1}, "journalIdentity": _TEXT,
        "processIdentity": _TEXT, "observedAt": _UTC, "monotonicNanos": _UINT,
        "monotonicOriginId": _TEXT, "previousAcceptedUtc": {"anyOf": [_UTC, {"type": "null"}]},
        "clockQualificationDigest": _DIGEST,
    }),
    PERMISSION_RULE_V1: _schema(PERMISSION_RULE_V1, {
        "kind": {"const": "EXECUTION_PERMISSION"}, "originalAuthorizationRef": {"type": "object"},
        "validFrom": _UTC, "expiresAt": _UTC,
        "replacement": {"enum": ["RETAIN_ORIGINAL", "SIGNED_CLOSING_PERMISSION_V1"]},
    }),
    DURATION_RULE_V1: _schema(DURATION_RULE_V1, {
        "kind": {"enum": ["RUN_WALL_BUDGET", "ATTEMPT_WALL_BUDGET"]},
        "originAt": _UTC, "limitSeconds": _UINT, "originalDeadlineAt": _UTC,
        "replacement": {"const": "RETAIN_ORIGINAL"}, "comparison": {"enum": ["LT", "LTE"]},
    }),
    FRESHNESS_RULE_V1: _schema(FRESHNESS_RULE_V1, {
        "kind": {"const": "EVIDENCE_FRESHNESS"},
        "receiptSelector": {"const": "QUALIFIED_CURRENT_OPERATION_EVIDENCE_V1"},
        "maxAgeSeconds": {"anyOf": [_UINT, {"type": "null"}]},
        "replacement": {"const": "RETAIN_ORIGINAL"},
    }),
    FIXED_DEADLINE_RULE_V1: _schema(FIXED_DEADLINE_RULE_V1, {
        "kind": {"enum": ["WORKER_LEASE", "PROCESS_GRACE", "OBSERVATION_IO"]},
        "sourceDeadlineRef": {"type": "object"},
        "deadlineAt": {"anyOf": [_UTC, {"type": "null"}]},
        "clockDomain": {"enum": ["QUALIFIED_UTC", "LOCAL_MONOTONIC"]},
        "replacement": {"const": "RETAIN_ORIGINAL"},
    }),
}


def _invalid(detail: str) -> None:
    raise LifecycleError("deadline-contract-invalid", detail)


def utc_microseconds(value: Any) -> datetime:
    """Parse exactly the new wire precision; preserve legacy raw bytes elsewhere."""
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        _invalid("Canonical UTC microsecond timestamp required")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)
    except ValueError:
        _invalid("UTC timestamp has an invalid calendar value")


def _uint(value: Any, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX:
        _invalid(f"{label} must be a bounded unsigned integer")
    return value


def _closed(value: Any, schema_id: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(DEADLINE_SCHEMAS[schema_id]["required"]):
        _invalid("Deadline record has missing or unknown fields")
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= 256:
        _invalid(f"{label} is invalid")
    return value


def _digest(value: Any, label: str) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        _invalid(f"{label} is not a digest")
    return value


def validate_clock_observation(value: Any) -> dict[str, Any]:
    record = _closed(value, CLOCK_OBSERVATION_V1)
    if record["schemaVersion"] != CLOCK_OBSERVATION_V1:
        _invalid("Clock observation version is unsupported")
    for key in ("journalIdentity", "processIdentity", "monotonicOriginId"):
        _text(record[key], key)
    current = utc_microseconds(record["observedAt"])
    previous = record["previousAcceptedUtc"]
    if previous is not None and current < utc_microseconds(previous):
        _invalid("Qualified local UTC high-water cannot move backward")
    _uint(record["monotonicNanos"], "monotonicNanos")
    _digest(record["clockQualificationDigest"], "clockQualificationDigest")
    return record


def _artifact_ref(value: Any) -> None:
    if type(value) is not dict or set(value) != {"path", "sha256", "bytes"}:
        _invalid("Artifact reference has missing or unknown fields")
    if type(value["path"]) is not str or not 1 <= len(value["path"]) <= 4096:
        _invalid("Artifact path is invalid")
    _digest(value["sha256"], "artifact digest")
    if not 1 <= _uint(value["bytes"], "artifact bytes") <= 1_048_576:
        _invalid("Artifact bytes are out of range")


def validate_permission_rule(value: Any) -> dict[str, Any]:
    rule = _closed(value, PERMISSION_RULE_V1)
    if rule["kind"] != "EXECUTION_PERMISSION" or rule["replacement"] not in {
        "RETAIN_ORIGINAL", "SIGNED_CLOSING_PERMISSION_V1"
    }:
        _invalid("Permission rule kind or replacement is unsupported")
    _artifact_ref(rule["originalAuthorizationRef"])
    if utc_microseconds(rule["validFrom"]) >= utc_microseconds(rule["expiresAt"]):
        _invalid("Original permission interval is invalid")
    return rule


def validate_duration_rule(value: Any) -> dict[str, Any]:
    rule = _closed(value, DURATION_RULE_V1)
    if rule["kind"] not in {"RUN_WALL_BUDGET", "ATTEMPT_WALL_BUDGET"} or rule["replacement"] != "RETAIN_ORIGINAL" or rule["comparison"] not in {"LT", "LTE"}:
        _invalid("Duration rule is not a retained qualified comparator")
    origin = utc_microseconds(rule["originAt"])
    limit = _uint(rule["limitSeconds"], "limitSeconds")
    try:
        expected = origin + timedelta(seconds=limit)
    except OverflowError:
        _invalid("Duration deadline overflows calendar range")
    if utc_microseconds(rule["originalDeadlineAt"]) != expected:
        _invalid("Duration deadline differs from original origin and limit")
    return rule


def validate_freshness_rule(value: Any) -> dict[str, Any]:
    rule = _closed(value, FRESHNESS_RULE_V1)
    if rule["kind"] != "EVIDENCE_FRESHNESS" or rule["receiptSelector"] != "QUALIFIED_CURRENT_OPERATION_EVIDENCE_V1" or rule["replacement"] != "RETAIN_ORIGINAL":
        _invalid("Freshness rule cannot be replaced by a closing grant")
    if rule["maxAgeSeconds"] is not None:
        _uint(rule["maxAgeSeconds"], "maxAgeSeconds")
    return rule


def validate_fixed_deadline_rule(value: Any) -> dict[str, Any]:
    rule = _closed(value, FIXED_DEADLINE_RULE_V1)
    if rule["kind"] not in {"WORKER_LEASE", "PROCESS_GRACE", "OBSERVATION_IO"} or rule["clockDomain"] not in {"QUALIFIED_UTC", "LOCAL_MONOTONIC"} or rule["replacement"] != "RETAIN_ORIGINAL":
        _invalid("Fixed native deadline cannot be replaced by a closing window")
    _artifact_ref(rule["sourceDeadlineRef"])
    if rule["deadlineAt"] is not None:
        utc_microseconds(rule["deadlineAt"])
    if rule["clockDomain"] == "QUALIFIED_UTC" and rule["deadlineAt"] is None:
        _invalid("Qualified UTC deadline requires an original timestamp")
    return rule


__all__ = [
    "CLOCK_OBSERVATION_V1", "DEADLINE_SCHEMAS", "DURATION_RULE_V1",
    "FIXED_DEADLINE_RULE_V1", "FRESHNESS_RULE_V1", "PERMISSION_RULE_V1", "utc_microseconds",
    "validate_clock_observation", "validate_duration_rule", "validate_fixed_deadline_rule",
    "validate_freshness_rule", "validate_permission_rule",
]
