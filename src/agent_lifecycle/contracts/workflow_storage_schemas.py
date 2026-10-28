"""Versioned immutable workflow references, independent of workflow code."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts.authority_io import normalize_authority_path
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES
from agent_lifecycle.contracts.errors import LifecycleError

STORAGE_VERSION = "agent-workflow-storage.v1"
REFERENCE_VERSION = "agent-workflow-storage-reference.v1"
WORKFLOW_STATE_V5 = "agent-workflow-state.v5"
LEAF_KINDS = {
    "ownershipReceipt": "ownership-receipt",
    "resultChangeSetEvidence": "result-change-set-evidence",
}
SNAPSHOT_KIND = "plan-snapshot"
MAX_CURRENT_TASKS = 32
MAX_SNAPSHOTS = 128
MAX_OPERATIONS = 2048
MAX_REACHABLE_OBJECTS = 4096
MAX_REACHABLE_BYTES = 64 * 1024 * 1024
MAX_RETAINED_BYTES = 128 * 1024 * 1024
IO_DEADLINE_SECONDS = 30.0
LINEAGE_FIELDS = (
    "runId",
    "packageId",
    "planRevision",
    "planDigest",
    "sourceRevision",
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def storage_error(message: str) -> LifecycleError:
    return LifecycleError("workflow-storage-invalid", message)


def capacity_error(
    category: str,
    current: int,
    required: int,
    limit: int,
) -> LifecycleError:
    return LifecycleError(
        "workflow-storage-capacity-exceeded",
        "Workflow storage capacity requires migration or reviewed replanning",
        {
            "category": category,
            "current": current,
            "required": required,
            "limit": limit,
            "recoveryRoute": "explicit migration or reviewed replanning",
        },
    )


def is_storage_reference(value: Any) -> bool:
    return isinstance(value, dict) and value.get(
        "schemaVersion",
    ) == (REFERENCE_VERSION)


def validate_storage_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "root"}:
        raise storage_error("Storage metadata has invalid fields")
    if value["schemaVersion"] != STORAGE_VERSION:
        raise storage_error("Unsupported storage version")
    root = value["root"]
    if not isinstance(root, str) or normalize_authority_path(root) != root:
        raise storage_error("Storage root is not a portable relative path")
    return value


def validate_storage_reference(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "kind",
        "sha256",
        "bytes",
        "path",
        "lineage",
        "itemCounts",
    }
    if not is_storage_reference(value) or set(value) != fields:
        raise storage_error("Immutable reference has invalid fields")
    if value["kind"] not in {*LEAF_KINDS.values(), SNAPSHOT_KIND}:
        raise storage_error("Immutable reference kind is unsupported")
    digest = value["sha256"]
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise storage_error("Immutable reference digest is invalid")
    if value["path"] != f"objects/{digest}.json":
        raise storage_error("Immutable reference path must match its digest")
    size = value["bytes"]
    if type(size) is not int or not 1 <= size <= MAX_JSON_INPUT_BYTES:
        raise storage_error("Immutable reference byte count is invalid")
    _validate_lineage(value["lineage"], value["kind"])
    counts = value["itemCounts"]
    if not isinstance(counts, dict) or any(
        not isinstance(
            key,
            str,
        )
        or type(count) is not int
        or count < 0
        for key, count in counts.items()
    ):
        raise storage_error("Immutable item counts are invalid")
    if is_initial_snapshot_lineage(value["kind"], value["lineage"]) and counts.get("tasks") != 0:
        raise storage_error("Initial snapshot requires zero tasks")
    return value


def is_initial_snapshot_lineage(kind: str, lineage: Any) -> bool:
    """Recognize only the native historical snapshot before first adoption."""
    return (
        kind == SNAPSHOT_KIND
        and isinstance(lineage, dict)
        and type(lineage.get("planRevision")) is int
        and lineage["planRevision"] == 0
        and lineage.get("planDigest") == ""
        and lineage.get("sourceRevision") == ""
    )


def _validate_lineage(lineage: Any, kind: str) -> None:
    keys = set(LINEAGE_FIELDS)
    if kind != SNAPSHOT_KIND:
        keys |= {"taskId", "attempt"}
    if not isinstance(lineage, dict) or set(lineage) != keys:
        raise storage_error("Immutable reference lineage fields are invalid")
    initial = is_initial_snapshot_lineage(kind, lineage)
    for key, item in lineage.items():
        if key in {"planRevision", "attempt"}:
            if type(item) is not int or item < 0:
                raise storage_error("Immutable lineage count is invalid")
        elif initial and key in {"planDigest", "sourceRevision"}:
            continue
        elif not isinstance(item, str) or not item:
            raise storage_error("Immutable lineage identity is invalid")
    if not initial and _DIGEST.fullmatch(lineage["planDigest"]) is None:
        raise storage_error("Immutable plan digest is invalid")


def item_counts(value: dict[str, Any]) -> dict[str, int]:
    """Bind every immediate array count without inventing body fields."""
    return {
        key: len(item)
        for key, item in value.items()
        if isinstance(
            item,
            list,
        )
    }


def validate_storage_counts(state: dict[str, Any]) -> None:
    for field, limit in (
        ("tasks", MAX_CURRENT_TASKS),
        ("priorSnapshots", MAX_SNAPSHOTS),
        ("operationLedger", MAX_OPERATIONS),
    ):
        default: Any = {} if field == "operationLedger" else []
        value = state.get(field, default)
        expected = dict if field == "operationLedger" else list
        if not isinstance(value, expected):
            raise storage_error(f"{field} has invalid storage shape")
        if len(value) > limit:
            raise capacity_error(field, len(value), len(value), limit)
    maximum = state.get("budgets", {}).get("maxTaskAttempts")
    if maximum is not None:
        if type(maximum) is not int or maximum < 1:
            raise storage_error("Frozen maxTaskAttempts is invalid")
        for task in state.get("tasks", []):
            if not isinstance(task, dict):
                raise storage_error("Task must be an object")
            history = task.get("attemptHistory", [])
            if not isinstance(history, list) or len(history) > maximum:
                raise storage_error("Task history exceeds frozen attempts")
