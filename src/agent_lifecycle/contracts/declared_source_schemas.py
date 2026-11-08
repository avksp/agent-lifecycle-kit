"""Closed declared project source data. Shape validity grants no authority."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, cast

from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.errors import require_condition
from agent_lifecycle.contracts.model_classes import ALLOWED_MODEL_CLASSES
from agent_lifecycle.contracts.paths import normalize_repo_path

SOURCE_USAGE_ROLES = ("coordinator", "worker", "check", "auditor", "retry", "compaction", "closeout")

PROJECT_POLICY = "alk-source-usage-completion-policy.v2"
PROJECT_ROUTE = "declared-project-source-v1"
PROJECT_CARRY = "agent-project-declared-source-carry.v1"
PROJECT_HEAD = "agent-project-declared-source-head.v1"
PROJECT_WINDOW = "agent-project-declared-source-window.v1"
PROJECT_PREFIX = "alk-source-authoring-registry-prefix.v2"
PROJECT_BINDING = "alk-source-usage-window-binding.v2"
OWNER_BINDINGS = "agent-project-source-owner-bindings.v1"
SOURCE_BLOB_LIMIT = 1_048_576
SOURCE_TOTAL_LIMIT = 8_388_608
DATA_LIMIT = 65_536
SAFE_INTEGER = 2**53 - 1


def require_declared(condition: bool, message: str) -> None:
    require_condition(condition, "declared-source-invalid", message)


def declared_object(value: Any, keys: set[str], version: str | None = None) -> dict[str, Any]:
    require_declared(isinstance(value, dict) and set(value) == keys, "closed object fields differ")
    require_declared(version is None or value.get("schemaVersion") == version, "source version differs")
    require_declared(len(canonical_bytes(value)) <= DATA_LIMIT, "source data exceeds byte limit")
    return cast(dict[str, Any], value)


def declared_label(value: Any) -> None:
    require_declared(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 1024, "invalid source label")


def declared_digest(value: Any) -> None:
    require_declared(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None, "invalid digest")


def declared_counter(value: Any, minimum: int = 0) -> None:
    require_declared(type(value) is int and minimum <= value <= SAFE_INTEGER, "invalid integer quantity")


def declared_rows(value: Any, maximum: int, minimum: int = 0) -> list[Any]:
    require_declared(isinstance(value, list) and minimum <= len(value) <= maximum, "source list exceeds bound")
    return cast(list[Any], value)


def validate_project_ref(value: Any) -> dict[str, Any]:
    ref = declared_object(value, {"path", "sha256", "bytes"})
    require_declared(
        isinstance(ref["path"], str)
        and len(ref["path"].encode("utf-8")) <= 4096
        and normalize_repo_path(ref["path"]) == ref["path"],
        "invalid reference path",
    )
    declared_digest(ref["sha256"])
    declared_counter(ref["bytes"], 1)
    return ref


def validate_project_policy(value: Any) -> dict[str, Any]:
    keys = {
        "schemaVersion",
        "mode",
        "adapterId",
        "adapterHost",
        "taskIds",
        "allowedModelClasses",
        "accountingKind",
        "openingRef",
        "sourceAuthoringRegistryRef",
        "actualCapConformance",
        "financialClosureAllowed",
        "financialSource",
    }
    policy = declared_object(value, keys, PROJECT_POLICY)
    require_declared(
        policy["mode"] == "SOURCE_AUTHORING_LIMITED"
        and policy["accountingKind"] == "PROJECT_DECLARED_SOURCE"
        and policy["actualCapConformance"] == "UNAVAILABLE"
        and policy["financialClosureAllowed"] is False,
        "source assurance cannot be promoted",
    )
    for key in ("adapterId", "adapterHost"):
        declared_label(policy[key])
    for key in ("taskIds", "allowedModelClasses"):
        rows = declared_rows(policy[key], 128, 1)
        for row in rows:
            declared_label(row)
        require_declared(len(set(rows)) == len(rows), "duplicate policy member")
    require_declared(set(policy["allowedModelClasses"]) <= ALLOWED_MODEL_CLASSES - {"no-model"}, "invalid model class")
    source = declared_object(policy["financialSource"], {"route", "sourceRoot", "headPath", "seedRef"})
    require_declared(source["route"] == PROJECT_ROUTE, "unregistered source route")
    for key in ("sourceRoot", "headPath"):
        require_declared(normalize_repo_path(source[key]) == source[key], "source path is not canonical")
    require_declared(source["headPath"].startswith(source["sourceRoot"] + "/"), "head outside source root")
    for ref in (source["seedRef"], policy["openingRef"], policy["sourceAuthoringRegistryRef"]):
        validate_project_ref(ref)
        require_declared(
            ref["bytes"] <= DATA_LIMIT and not ref["path"].startswith(source["sourceRoot"] + "/"),
            "immutable source input overlaps mutable source root",
        )
    return policy


def validate_owner_bindings(value: Any) -> dict[str, Any]:
    data = declared_object(value, {"schemaVersion", "requiredRoles", "ownerBindings"}, OWNER_BINDINGS)
    require_declared(data["requiredRoles"] == list(SOURCE_USAGE_ROLES), "all source roles required")
    actors: set[str] = set()
    tasks: set[str] = set()
    for owner in declared_rows(data["ownerBindings"], 128, 1):
        declared_object(owner, {"actorId", "role", "taskIds"})
        declared_label(owner["actorId"])
        require_declared(
            owner["role"] in SOURCE_USAGE_ROLES and owner["actorId"] not in actors, "duplicate actor or invalid role"
        )
        actors.add(owner["actorId"])
        for task in declared_rows(owner["taskIds"], 128, 1):
            declared_label(task)
            require_declared(task not in tasks, "duplicate task attribution")
            tasks.add(task)
    return data


def validate_unknown_intervals(value: Any, digests: set[str]) -> list[Any]:
    rows = declared_rows(value, 128, 1)
    ids: set[str] = set()
    for row in rows:
        declared_object(row, {"id", "roles", "reason", "sourceRefDigest", "status"})
        declared_label(row["id"])
        declared_label(row["reason"])
        roles = declared_rows(row["roles"], 7, 1)
        for role in roles:
            declared_label(role)
        declared_digest(row["sourceRefDigest"])
        require_declared(
            len(set(roles)) == len(roles) and set(roles) <= set(SOURCE_USAGE_ROLES), "invalid unknown roles"
        )
        require_declared(
            row["id"] not in ids and row["sourceRefDigest"] in digests and row["status"] == "UNAVAILABLE",
            "unknown interval lost source or repeated identity",
        )
        ids.add(row["id"])
    return rows


def validate_project_carry(value: Any) -> dict[str, Any]:
    data = declared_object(
        value,
        {
            "schemaVersion",
            "sourceScopeId",
            "originalRunStartedAt",
            "originalRunDeadlineAt",
            "sourceRefs",
            "declaredUnitRecords",
            "knownPartials",
            "unknownIntervals",
            "financialAssurance",
        },
        PROJECT_CARRY,
    )
    declared_label(data["sourceScopeId"])
    for key in ("originalRunStartedAt", "originalRunDeadlineAt"):
        declared_label(data[key])
    try:
        started = datetime.fromisoformat(data["originalRunStartedAt"].replace("Z", "+00:00"))
        deadline = datetime.fromisoformat(data["originalRunDeadlineAt"].replace("Z", "+00:00"))
    except ValueError:
        require_declared(False, "invalid original source timestamp")
        raise AssertionError("unreachable") from None
    require_declared(
        started.tzinfo is not None and deadline.tzinfo is not None and started < deadline,
        "original source window is invalid",
    )
    require_declared(data["financialAssurance"] == "DECLARED_SOURCE_ONLY", "source assurance differs")
    digests: set[str] = set()
    paths: set[str] = set()
    total = 0
    for row in declared_rows(data["sourceRefs"], 32, 1):
        declared_object(row, {"originalPath", "path", "sha256", "bytes"})
        declared_label(row["originalPath"])
        validate_project_ref({key: row[key] for key in ("path", "sha256", "bytes")})
        require_declared(
            row["path"].endswith(".raw") and row["bytes"] <= SOURCE_BLOB_LIMIT and row["path"] not in paths,
            "invalid original snapshot",
        )
        digests.add(row["sha256"])
        paths.add(row["path"])
        total += row["bytes"]
    require_declared(total <= SOURCE_TOTAL_LIMIT, "source snapshots exceed total limit")
    ids: set[str] = set()
    for row in declared_rows(data["declaredUnitRecords"], 256, 1):
        declared_object(row, {"id", "role", "unit", "quantity", "bookingKind", "originRefDigest"})
        for key in ("id", "unit"):
            declared_label(row[key])
        declared_counter(row["quantity"], 1)
        declared_label(row["bookingKind"])
        declared_digest(row["originRefDigest"])
        require_declared(
            row["id"] not in ids
            and (row["role"] is None or row["role"] in SOURCE_USAGE_ROLES)
            and row["bookingKind"] in {"CARRIED_FORWARD", "CONSERVATIVE_RESERVATION", "DECLARED_BOOKING"}
            and row["originRefDigest"] in digests,
            "invalid declared unit provenance",
        )
        ids.add(row["id"])
    for row in declared_rows(data["knownPartials"], 256):
        declared_object(row, {"metric", "unit", "value", "sourceRefDigest"})
        declared_label(row["metric"])
        declared_label(row["unit"])
        require_declared(
            type(row["value"]) in (int, float) and 0 <= row["value"] <= SAFE_INTEGER,
            "invalid nonnegative labelled partial",
        )
        declared_digest(row["sourceRefDigest"])
        require_declared(row["sourceRefDigest"] in digests, "partial lacks source")
    validate_unknown_intervals(data["unknownIntervals"], digests)
    return data


def validate_project_head(value: Any) -> dict[str, Any]:
    data = declared_object(
        value,
        {
            "schemaVersion",
            "seedSha256",
            "sequence",
            "previousHeadSha256",
            "openingHeadSha256",
            "windows",
            "unknownIntervals",
            "financialClosure",
        },
        PROJECT_HEAD,
    )
    declared_digest(data["seedSha256"])
    declared_counter(data["sequence"])
    for key in ("previousHeadSha256", "openingHeadSha256"):
        if data["sequence"] == 0:
            require_declared(data[key] is None, "opening must be hash-only without self reference")
        else:
            declared_digest(data[key])
    rows = declared_rows(data["windows"], 128)
    require_declared(len(rows) == data["sequence"], "window sequence truncated")
    for row in rows:
        validate_project_ref(row)
        require_declared(row["bytes"] <= DATA_LIMIT, "window reference exceeds limit")
    require_declared(len({row["path"] for row in rows}) == len(rows), "duplicate window path")
    require_declared(data["financialClosure"] == "OPEN_UNAVAILABLE", "financial closure forbidden")
    declared_rows(data["unknownIntervals"], 128, 1)
    return data


def validate_project_binding(value: Any) -> dict[str, Any]:
    keys = {
        "schemaVersion",
        "bindingKind",
        "semanticOperationId",
        "runId",
        "packageId",
        "taskId",
        "attempt",
        "planDigest",
        "sourceRevision",
        "routeDecisionDigest",
        "sourceUsagePolicyDigest",
        "actorId",
        "role",
        "originalWindowId",
        "originalCostScope",
        "sourceInputSubjectDigest",
    }
    data = declared_object(value, keys, PROJECT_BINDING)
    require_declared(
        data["bindingKind"] == "PROJECT_DECLARED_SOURCE"
        and data["role"] in SOURCE_USAGE_ROLES
        and data["originalCostScope"] == "SOURCE_AUTHORING_LIMITED",
        "window source kind differs",
    )
    for key in ("semanticOperationId", "runId", "packageId", "taskId", "sourceRevision", "actorId", "originalWindowId"):
        declared_label(data[key])
    declared_counter(data["attempt"], 1)
    for key in ("planDigest", "routeDecisionDigest", "sourceUsagePolicyDigest", "sourceInputSubjectDigest"):
        declared_digest(data[key])
    require_declared(
        re.fullmatch("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", data["originalWindowId"]) is not None, "unsafe window id"
    )
    return data


def validate_project_window(value: Any) -> dict[str, Any]:
    data = declared_object(
        value,
        {
            "schemaVersion",
            "id",
            "sequence",
            "openingSha256",
            "previousHeadSha256",
            "binding",
            "declaredTokenHold",
            "sourceContextRefs",
            "observations",
            "costStatus",
            "actualTokens",
            "actualUSD",
            "financialClosure",
        },
        PROJECT_WINDOW,
    )
    binding = validate_project_binding(data["binding"])
    require_declared(data["id"] == binding["originalWindowId"], "window id differs from binding")
    declared_counter(data["sequence"], 1)
    declared_counter(data["declaredTokenHold"], 1)
    declared_digest(data["openingSha256"])
    declared_digest(data["previousHeadSha256"])
    for ref in declared_rows(data["sourceContextRefs"], 256):
        validate_project_ref(ref)
        require_declared(ref["bytes"] <= DATA_LIMIT, "context exceeds receipt bound")
    require_declared(
        data["observations"] == []
        and data["costStatus"] == "UNAVAILABLE"
        and data["actualTokens"] is None
        and data["actualUSD"] is None
        and data["financialClosure"] == "OPEN_UNAVAILABLE",
        "source cannot settle unknown usage",
    )
    return data


def validate_project_prefix(value: Any) -> dict[str, Any]:
    data = declared_object(
        value,
        {
            "schemaVersion",
            "openingHeadSha256",
            "requiredRoles",
            "ownerBindings",
            "historicalSourceRefs",
            "unknownIntervals",
        },
        PROJECT_PREFIX,
    )
    validate_owner_bindings(
        {
            "schemaVersion": OWNER_BINDINGS,
            "requiredRoles": data["requiredRoles"],
            "ownerBindings": data["ownerBindings"],
        }
    )
    declared_digest(data["openingHeadSha256"])
    for ref in declared_rows(data["historicalSourceRefs"], 128, 1):
        validate_project_ref(ref)
        require_declared(ref["bytes"] <= DATA_LIMIT, "prefix reference exceeds bound")
    declared_rows(data["unknownIntervals"], 128, 1)
    return data
