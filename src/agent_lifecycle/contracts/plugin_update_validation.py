"""Bounded contextual validation shared by update advice, without dispatch."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.plugin_update_schemas import (
    PLUGIN_UPDATE_SCHEMAS,
    UPDATE_ACTIONS,
    UPDATE_CACHE_SCHEMA,
    UPDATE_DOMAINS,
    UPDATE_IMPACT_SCHEMA,
    UPDATE_INVENTORY_SCHEMA,
    UPDATE_MODES,
    UPDATE_REPORT_SCHEMA,
    UPDATE_REQUEST_SCHEMA,
    UPDATE_SOURCE,
)

MAX_UPDATE_BYTES = 262144
MAX_PLAN_INPUT_BYTES = 8388608
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?\Z")
_HEX = re.compile(r"[0-9a-f]+\Z")


def require_update(condition: bool, reason: str) -> None:
    if not condition:
        raise LifecycleError("plugin-update-invalid", reason)


def update_bounds(value: Any, depth: int = 0) -> None:
    require_update(depth <= 16, "update JSON exceeds depth16")
    if isinstance(value, str):
        require_update(len(value) <= 4096, "update string exceeds4096")
    elif isinstance(value, dict):
        for key, child in value.items():
            require_update(isinstance(key, str) and len(key) <= 4096, "invalid JSON member")
            update_bounds(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            update_bounds(child, depth + 1)


def update_json(data: bytes) -> dict[str, Any]:
    require_update(len(data) <= MAX_UPDATE_BYTES, "update input exceeds256KiB")
    value = load_json_object(data)
    update_bounds(value)
    return value


def read_update_json(root: Path, name: str) -> dict[str, Any]:
    return update_json(read_stable_repository_file(root, name, max_bytes=MAX_UPDATE_BYTES))


def update_object(value: Any, fields: set[str], required: set[str]) -> dict[str, Any]:
    require_update(isinstance(value, dict), "expected an update object")
    require_update(set(value) <= fields and required <= set(value), "unknown or missing update fields")
    return value


def _envelope(value: Any, schema: str) -> dict[str, Any]:
    definition = PLUGIN_UPDATE_SCHEMAS[schema]
    obj = update_object(value, set(definition["properties"]), set(definition["required"]))
    require_update(obj["schemaVersion"] == schema, "unsupported update schema")
    update_bounds(obj)
    require_update(len(canonical_bytes(obj)) <= MAX_UPDATE_BYTES, "update object exceeds256KiB")
    return obj


def update_text(value: Any) -> str:
    require_update(isinstance(value, str) and 0 < len(value) <= 4096, "invalid update text")
    return value


def update_digest(value: Any, length: int = 64) -> str:
    require_update(
        isinstance(value, str) and len(value) == length and bool(_HEX.fullmatch(value)), "invalid update digest"
    )
    return value


def update_version(value: Any) -> str:
    require_update(
        isinstance(value, str) and len(value) <= 128 and bool(_VERSION.fullmatch(value)),
        "expected an exact release version",
    )
    match = _VERSION.fullmatch(value)
    if match and match[4] is not None:
        require_update(
            all(part and (not part.isdigit() or len(part) == 1 or part[0] != "0") for part in match[4].split(".")),
            "invalid prerelease identifier",
        )
    return value


def update_strings(value: Any, maximum: int) -> list[str]:
    require_update(isinstance(value, list) and len(value) <= maximum, "invalid bounded string list")
    result = [update_text(item) for item in value]
    require_update(len(set(result)) == len(result), "duplicate update identifier")
    return result


def validate_update_request(value: Any) -> dict[str, Any]:
    obj = _envelope(value, UPDATE_REQUEST_SCHEMA)
    require_update(obj.get("mode", "manual") in UPDATE_MODES, "unsupported update mode")
    require_update(obj.get("channel", "stable") in ("stable", "prerelease"), "unsupported update channel")
    require_update(obj.get("source", UPDATE_SOURCE) == UPDATE_SOURCE, "untrusted update source")
    pin = obj.get("pin")
    if pin is not None:
        require_update(isinstance(pin, str) and pin.startswith("v"), "pin must name an exact release tag")
        update_version(pin[1:])
    if "targetVersion" in obj:
        update_version(obj["targetVersion"])
        require_update(pin is None or pin == "v" + obj["targetVersion"], "target conflicts with immutable pin")
    if "trustedTargetCommit" in obj:
        update_digest(obj["trustedTargetCommit"], 40)
    if "triggerQualified" in obj:
        require_update(type(obj["triggerQualified"]) is bool, "trigger flag must be boolean")
    observations = update_object(
        obj.get("observations", {}), {"installedPlugin", "loadedInstructions", "runtime"}, set()
    )
    for observation in observations.values():
        record = update_object(observation, {"version", "provenance"}, {"version"})
        if record["version"] is not None:
            update_version(record["version"])
        require_update(
            record.get("provenance", "DECLARED") in ("DECLARED", "UNAVAILABLE"),
            "caller observation cannot attest host identity",
        )
    host = update_object(obj.get("host", {}), {"adapterId", "version", "scope"}, set())
    for key in ("adapterId", "version"):
        if key in host:
            update_text(host[key])
    require_update(host.get("scope", "unknown") in ("unknown", "user", "project", "isolated"), "invalid host scope")
    return obj


def validate_release_impact(value: Any) -> dict[str, Any]:
    obj = _envelope(value, UPDATE_IMPACT_SCHEMA)
    update_version(obj["version"])
    require_update(obj["origin"] == UPDATE_SOURCE, "untrusted descriptor origin")
    if obj["sourceCommit"] is not None:
        update_digest(obj["sourceCommit"], 40)
    for version in update_strings(obj["baseVersions"], 32):
        update_version(version)
    update_strings(obj["exclusions"], 64)
    domains = update_object(obj["domains"], set(UPDATE_DOMAINS), set())
    for domain in domains.values():
        item = update_object(
            domain,
            {"identifiers", "coverage", "semanticReview", "evidenceRefs"},
            {"identifiers", "coverage", "semanticReview", "evidenceRefs"},
        )
        update_strings(item["identifiers"], 256)
        refs = update_strings(item["evidenceRefs"], 32)
        require_update(item["coverage"] in ("PARTIAL", "COMPLETE"), "invalid descriptor coverage")
        require_update(item["semanticReview"] in ("UNVERIFIED", "REVIEWED"), "invalid semantic review")
        require_update(item["semanticReview"] != "REVIEWED" or bool(refs), "reviewed meaning needs evidence refs")
    require_update(isinstance(obj["changes"], list) and len(obj["changes"]) <= 512, "too many changes")
    seen = set()
    for change in obj["changes"]:
        row = update_object(
            change,
            {"domain", "identifier", "impact", "reason", "proposedEdit"},
            {"domain", "identifier", "impact", "reason"},
        )
        require_update(row["domain"] in UPDATE_DOMAINS, "unknown change domain")
        identifier = update_text(row["identifier"])
        require_update((row["domain"], identifier) not in seen, "duplicate change record")
        seen.add((row["domain"], identifier))
        require_update(row["impact"] in ("UNCHANGED", "ADAPTATION_REQUIRED", "UNKNOWN"), "invalid change impact")
        update_text(row["reason"])
        if "proposedEdit" in row:
            _validate_edit(row["proposedEdit"])
    return obj


def _validate_edit(value: Any) -> None:
    row = update_object(
        value,
        {"path", "pointer", "expectedValue", "proposedValue"},
        {"path", "pointer", "expectedValue", "proposedValue"},
    )
    normalize_repo_path(row["path"])
    pointer = update_text(row["pointer"])
    require_update(pointer.startswith("/") and not re.search(r"~(?![01])", pointer), "invalid edit pointer")
    for key in ("expectedValue", "proposedValue"):
        require_update(row[key] is None or type(row[key]) in (str, bool, int), "edit values must be literals")


def validate_plan_inventory(value: Any) -> dict[str, Any]:
    obj = _envelope(value, UPDATE_INVENTORY_SCHEMA)
    require_update(isinstance(obj["plans"], list) and 0 < len(obj["plans"]) <= 32, "expected1..32 explicit plans")
    if "currentVersion" in obj:
        update_version(obj["currentVersion"])
    seen = set()
    for plan in obj["plans"]:
        row = update_object(plan, {"manifest", "lock", "state"}, {"manifest"})
        for path in row.values():
            normalize_repo_path(path)
        require_update(row["manifest"] not in seen, "duplicate plan manifest")
        seen.add(row["manifest"])
    return obj


def validate_update_report(value: Any) -> dict[str, Any]:
    obj = _envelope(value, UPDATE_REPORT_SCHEMA)
    require_update(obj["action"] in UPDATE_ACTIONS, "unsupported report action")
    require_update(
        obj["status"] in PLUGIN_UPDATE_SCHEMAS[UPDATE_REPORT_SCHEMA]["properties"]["status"]["enum"],
        "unsupported report status",
    )
    update_digest(obj["requestDigest"])
    require_update(
        obj["authorityClaimed"] is False
        and type(obj["modelCallsStarted"]) is int
        and obj["modelCallsStarted"] == 0
        and type(obj["nativeProcessesStarted"]) is int
        and obj["nativeProcessesStarted"] == 0,
        "advice cannot claim execution or authority",
    )
    require_update(isinstance(obj["inputs"], dict) and isinstance(obj["details"], dict), "invalid report bodies")
    for item in obj["inputs"].values():
        update_text(item)
    return obj


def update_report(
    action: str, status: str, request: dict[str, Any], details: dict[str, Any], inputs: dict[str, str] | None = None
) -> dict[str, Any]:
    return validate_update_report(
        {
            "schemaVersion": UPDATE_REPORT_SCHEMA,
            "action": action,
            "status": status,
            "requestDigest": canonical_digest(validate_update_request(request)),
            "inputs": inputs or {},
            "details": details,
            "authorityClaimed": False,
            "modelCallsStarted": 0,
            "nativeProcessesStarted": 0,
        }
    )


def validate_update_cache(value: Any) -> dict[str, Any]:
    obj = _envelope(value, UPDATE_CACHE_SCHEMA)
    update_digest(obj["policyDigest"])
    require_update(type(obj["observedAt"]) is int and 0 <= obj["observedAt"] <= 4102444800, "invalid cache timestamp")
    require_update(isinstance(obj["candidate"], dict), "invalid cached candidate")
    return obj
