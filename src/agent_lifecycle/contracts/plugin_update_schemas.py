"""Inert public records for optional update advice; none grants authority."""

from __future__ import annotations

from typing import Any

UPDATE_SOURCE = "https://github.com/avksp/agent-lifecycle-kit"
UPDATE_DOMAINS = (
    "schema",
    "cli",
    "path",
    "profile",
    "host",
    "quality",
    "review",
    "evidence",
    "authority",
)
UPDATE_MODES = ("off", "manual", "notify", "ask", "safe-auto")
UPDATE_ACTIONS = ("check", "assess", "offer", "install", "reconcile")
UPDATE_REQUEST_SCHEMA = "agent-plugin-update-request.v1"
UPDATE_IMPACT_SCHEMA = "agent-plugin-release-impact.v1"
UPDATE_INVENTORY_SCHEMA = "agent-plugin-plan-inventory.v1"
UPDATE_REPORT_SCHEMA = "agent-plugin-update-report.v1"
UPDATE_CACHE_SCHEMA = "agent-plugin-update-cache.v1"
UPDATE_FAILURE_REASONS = (
    "plugin-update-invalid",
    "plugin-update-network-timeout",
    "plugin-update-network-unavailable",
    "plugin-update-metadata-unavailable",
    "plugin-update-metadata-invalid",
)


def _object(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(required)}


def _strings(maximum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": maximum,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 4096},
    }


_TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
_VERSION = {"type": "string", "pattern": r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"}
_OBSERVATION = _object(
    {
        "version": {"type": ["string", "null"], "maxLength": 128},
        "provenance": {"enum": ["DECLARED", "UNAVAILABLE"]},
    },
    ("version",),
)
_DOMAIN = _object(
    {
        "identifiers": _strings(256),
        "coverage": {"enum": ["PARTIAL", "COMPLETE"]},
        "semanticReview": {"enum": ["UNVERIFIED", "REVIEWED"]},
        "evidenceRefs": _strings(32),
    },
    ("identifiers", "coverage", "semanticReview", "evidenceRefs"),
)
_EDIT = _object(
    {"path": _TEXT, "pointer": _TEXT, "expectedValue": {}, "proposedValue": {}},
    ("path", "pointer", "expectedValue", "proposedValue"),
)
_CHANGE = _object(
    {
        "domain": {"enum": list(UPDATE_DOMAINS)},
        "identifier": _TEXT,
        "impact": {"enum": ["UNCHANGED", "ADAPTATION_REQUIRED", "UNKNOWN"]},
        "reason": _TEXT,
        "proposedEdit": _EDIT,
    },
    ("domain", "identifier", "impact", "reason"),
)
_PLAN = _object({"manifest": _TEXT, "lock": _TEXT, "state": _TEXT}, ("manifest",))

PLUGIN_UPDATE_SCHEMAS = {
    UPDATE_REQUEST_SCHEMA: _object(
        {
            "schemaVersion": {"const": UPDATE_REQUEST_SCHEMA},
            "mode": {"enum": list(UPDATE_MODES)},
            "channel": {"enum": ["stable", "prerelease"]},
            "pin": {"type": ["string", "null"], "maxLength": 128},
            "targetVersion": _VERSION,
            "source": {"const": UPDATE_SOURCE},
            "trustedTargetCommit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "triggerQualified": {"type": "boolean"},
            "observations": _object(
                {name: _OBSERVATION for name in ("installedPlugin", "loadedInstructions", "runtime")}
            ),
            "host": _object(
                {"adapterId": _TEXT, "version": _TEXT, "scope": {"enum": ["unknown", "user", "project", "isolated"]}}
            ),
        },
        ("schemaVersion",),
    ),
    UPDATE_IMPACT_SCHEMA: _object(
        {
            "schemaVersion": {"const": UPDATE_IMPACT_SCHEMA},
            "version": _VERSION,
            "sourceCommit": {"type": ["string", "null"], "pattern": "^[0-9a-f]{40}$"},
            "origin": {"const": UPDATE_SOURCE},
            "baseVersions": _strings(32),
            "domains": _object(dict.fromkeys(UPDATE_DOMAINS, _DOMAIN)),
            "changes": {"type": "array", "maxItems": 512, "items": _CHANGE},
            "exclusions": _strings(64),
        },
        ("schemaVersion", "version", "sourceCommit", "origin", "baseVersions", "domains", "changes", "exclusions"),
    ),
    UPDATE_INVENTORY_SCHEMA: _object(
        {
            "schemaVersion": {"const": UPDATE_INVENTORY_SCHEMA},
            "plans": {"type": "array", "maxItems": 32, "minItems": 1, "items": _PLAN},
            "currentVersion": _VERSION,
        },
        ("schemaVersion", "plans"),
    ),
    UPDATE_REPORT_SCHEMA: _object(
        {
            "schemaVersion": {"const": UPDATE_REPORT_SCHEMA},
            "action": {"enum": list(UPDATE_ACTIONS)},
            "status": {
                "enum": [
                    "AVAILABLE",
                    "CURRENT",
                    "OFF",
                    "STALE",
                    "UNAVAILABLE",
                    "UNSUPPORTED",
                    "ASSESSED",
                    "OFFERED",
                    "UNKNOWN",
                    "DRIFT",
                ]
            },
            "requestDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "inputs": {"type": "object", "additionalProperties": _TEXT},
            "details": {"type": "object"},
            "authorityClaimed": {"const": False},
            "modelCallsStarted": {"const": 0},
            "nativeProcessesStarted": {"const": 0},
        },
        (
            "schemaVersion",
            "action",
            "status",
            "requestDigest",
            "inputs",
            "details",
            "authorityClaimed",
            "modelCallsStarted",
            "nativeProcessesStarted",
        ),
    ),
    UPDATE_CACHE_SCHEMA: _object(
        {
            "schemaVersion": {"const": UPDATE_CACHE_SCHEMA},
            "policyDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "observedAt": {"type": ["integer", "null"], "minimum": 0, "maximum": 4102444800},
            "candidate": {"type": ["object", "null"]},
            "lastAttemptAt": {"type": "integer", "minimum": 0, "maximum": 4102444800},
            "lastFailureReason": {"enum": list(UPDATE_FAILURE_REASONS)},
        },
        ("schemaVersion", "policyDigest", "observedAt", "candidate"),
    ),
}
PLUGIN_UPDATE_SCHEMAS[UPDATE_CACHE_SCHEMA]["oneOf"] = [
    {"properties": {"observedAt": {"type": "integer"}, "candidate": {"type": "object"}}},
    {
        "properties": {"observedAt": {"type": "null"}, "candidate": {"type": "null"}},
        "required": ["lastAttemptAt", "lastFailureReason"],
    },
]
PLUGIN_UPDATE_SCHEMAS[UPDATE_CACHE_SCHEMA]["dependentRequired"] = {"lastFailureReason": ["lastAttemptAt"]}
for _name, _schema in PLUGIN_UPDATE_SCHEMAS.items():
    _schema.update({"$id": _name, "$schema": "https://json-schema.org/draft/2020-12/schema"})
