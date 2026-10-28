"""Pure v5 compaction and bounded, complete immutable graph validation.

Callers serialize mutations using the existing workflow transaction. Preparation
never writes. Validation inspects unselected history too; persistence must run
only after the prospective state/event/checkpoint have all passed preflight.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.canonical import (
    MAX_JSON_INPUT_BYTES,
    canonical_bytes,
    canonical_digest,
    load_json_object,
    prepare_json_object,
    sha256_hex,
)
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.workflow_storage_context import (
    CheckedStorageWrites,
    StorageOperation,
    choose_operation,
    storage_operation,
    write_set_digest,
)
from agent_lifecycle.contracts.workflow_storage_io import (
    check_deadline,
    persist_objects,
    preflight_objects,
    read_object,
    retained_bytes,
    storage_path,
)
from agent_lifecycle.contracts.workflow_storage_schemas import (
    LEAF_KINDS,
    LINEAGE_FIELDS,
    MAX_CURRENT_TASKS,
    MAX_OPERATIONS,
    MAX_REACHABLE_BYTES,
    MAX_REACHABLE_OBJECTS,
    MAX_RETAINED_BYTES,
    MAX_SNAPSHOTS,
    REFERENCE_VERSION,
    SNAPSHOT_KIND,
    STORAGE_VERSION,
    WORKFLOW_STATE_V5,
    capacity_error,
    is_initial_snapshot_lineage,
    is_storage_reference,
    item_counts,
    storage_error,
    validate_storage_counts,
    validate_storage_metadata,
    validate_storage_reference,
)

_FINANCIAL_ROLE = "HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING"
_BODY_SCHEMAS = {
    "ownership-receipt": "agent-task-ownership-receipt.v1",
    "result-change-set-evidence": "agent-task-change-set-evidence.v1",
}


@dataclass(frozen=True)
class PreparedStorage:
    state: dict[str, Any]
    objects: dict[str, bytes]

    def writes(
        self,
        root: Path,
        *,
        operation: StorageOperation | None = None,
    ) -> dict[Path, bytes]:
        """Exact sidecar bytes for existing observer/policy composition."""
        if operation is not None:
            operation.bind(root, self.state)
        base = storage_path(root, self.state["storage"])
        return {base / name: data for name, data in self.objects.items()}


@dataclass(frozen=True)
class StorageValidation:
    object_count: int
    reachable_bytes: int
    retained_bytes: int
    object_reads: int
    elapsed_seconds: float
    warnings: tuple[str, ...]


def _lineage(context: dict[str, Any]) -> dict[str, Any]:
    return {key: context.get(key) for key in LINEAGE_FIELDS}


def _task_lineage(
    context: dict[str, Any],
    task: dict[str, Any],
    revisions: dict[str, int],
) -> dict[str, Any]:
    result = _lineage(context)
    result.update(taskId=task.get("id"), attempt=task.get("attempt", 0))
    # Accepted tasks copied into a later plan keep original evidence lineage.
    receipt = task.get("ownershipReceipt")
    if isinstance(receipt, dict):
        original: Any = receipt
        if is_storage_reference(receipt):
            original = receipt.get("lineage")
        if isinstance(original, dict):
            for key in ("planRevision", "planDigest", "sourceRevision"):
                if original.get(key) is not None:
                    result[key] = original[key]
    digest = result["planDigest"]
    if digest not in revisions:
        raise storage_error("Original evidence plan lineage is unavailable")
    if is_storage_reference(
        receipt,
    ) and (result["planRevision"] != revisions[digest]):
        raise storage_error("Original evidence plan revision mismatch")
    result["planRevision"] = revisions[digest]
    return result


def _plan_revisions(state: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for snapshot in [state, *state.get("priorSnapshots", [])]:
        if not isinstance(snapshot, dict):
            raise storage_error("Plan snapshot must be an object")
        identity = snapshot
        if is_storage_reference(snapshot):
            identity = snapshot["lineage"]
        digest = identity.get("planDigest")
        revision = identity.get("planRevision")
        if not isinstance(digest, str) or type(revision) is not int:
            raise storage_error("Plan lineage identity is invalid")
        if digest in result and result[digest] != revision:
            raise storage_error("Plan digest has ambiguous revisions")
        result[digest] = revision
    return result


def _task_records(task: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Visit bounded task history and preserved financial task copies."""
    yield task
    history = task.get("attemptHistory", [])
    if not isinstance(history, list):
        raise storage_error("Task attempt history must be an array")
    for attempt in history:
        if not isinstance(attempt, dict):
            raise storage_error("Task attempt history entry must be an object")
        yield attempt
    for field in ("priorFinancialObligations", "planIncompatibility"):
        previous = task.get(field)
        if field == "planIncompatibility" and isinstance(previous, dict):
            previous = previous.get("financialObligations")
        if isinstance(previous, dict):
            yield from _task_records(previous)


def _task_slots(
    context: dict[str, Any],
    revisions: dict[str, int],
) -> Iterator[tuple[dict[str, Any], str, str, dict[str, Any]]]:
    tasks = context.get("tasks", [])
    if not isinstance(tasks, list):
        raise storage_error("Snapshot tasks must be an array")
    for task in tasks:
        if not isinstance(task, dict):
            raise storage_error("Task must be an object")
        for record in _task_records(task):
            lineage = _task_lineage(
                context,
                {"id": task.get("id"), **record},
                revisions,
            )
            for field, kind in LEAF_KINDS.items():
                if field in record:
                    yield record, field, kind, lineage


def _forbid_nested_references(
    value: Any,
    allowed: set[int],
    *,
    forbid_evidence: bool = False,
) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            schema = item.get("schemaVersion")
            if forbid_evidence and (any(key in item for key in LEAF_KINDS) or schema in _BODY_SCHEMAS.values()):
                raise storage_error("Initial snapshot contains task evidence")
            reference_schema = "agent-workflow-storage-reference."
            if isinstance(schema, str) and schema.startswith(reference_schema):
                validate_storage_reference(item)
                if id(item) not in allowed:
                    raise storage_error("Reference outside a permitted slot")
                continue
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _bounded_bytes(value: dict[str, Any], category: str) -> bytes:
    try:
        return prepare_json_object(value, label=category)
    except LifecycleError as exc:
        if exc.code != "json-input-too-large":
            raise
        required = len(canonical_bytes(value)) + 1
        raise capacity_error(
            category,
            required,
            required,
            MAX_JSON_INPUT_BYTES,
        ) from None


def _prepare_reference(
    value: Any,
    kind: str,
    lineage: dict[str, Any],
    objects: dict[str, bytes],
) -> dict[str, Any]:
    if is_storage_reference(value):
        reference = validate_storage_reference(value)
        _require_reference_context(reference, kind, lineage)
        return reference
    if not isinstance(value, dict):
        raise storage_error("Immutable body must be an object")
    _validate_body_kind(value, kind)
    _require_initial_snapshot_body(value, kind, lineage)
    data = _bounded_bytes(value, kind)
    digest = sha256_hex(data[:-1])
    name = f"objects/{digest}.json"
    existing = objects.setdefault(name, data)
    if existing != data:
        raise storage_error("Ambiguous canonical object identity")
    reference = {
        "schemaVersion": REFERENCE_VERSION,
        "kind": kind,
        "sha256": digest,
        "bytes": len(data),
        "path": name,
        "lineage": lineage,
        "itemCounts": item_counts(value),
    }
    validate_storage_reference(reference)
    return reference


def _compact_tasks(
    context: dict[str, Any],
    objects: dict[str, bytes],
    revisions: dict[str, int],
) -> None:
    for record, field, kind, lineage in _task_slots(context, revisions):
        record[field] = _prepare_reference(
            record[field],
            kind,
            lineage,
            objects,
        )


def prepare_storage(
    state: dict[str, Any],
    *,
    storage_root: str | None = None,
    operation: StorageOperation | None = None,
) -> PreparedStorage:
    """Return a compact copy and exact create-only bytes without any I/O."""
    if state.get("schemaVersion") not in {
        "agent-workflow-state.v4",
        WORKFLOW_STATE_V5,
    }:
        raise storage_error("Storage preparation requires v4 or v5 input")
    operation = operation or StorageOperation.current()
    if operation is not None:
        operation, _ = choose_operation(operation.root, operation)
        operation.bind(operation.root, state)
    compact = deepcopy(state)
    validate_storage_counts(compact)
    metadata = compact.get("storage")
    if metadata is None:
        if storage_root is None:
            raise storage_error("Initial preparation requires storage_root")
        metadata = {"schemaVersion": STORAGE_VERSION, "root": storage_root}
    validate_storage_metadata(metadata)
    if storage_root is not None and metadata["root"] != storage_root:
        raise storage_error("Existing immutable storage root cannot change")
    compact["schemaVersion"] = WORKFLOW_STATE_V5
    compact["storage"] = metadata
    objects: dict[str, bytes] = {}
    revisions = _plan_revisions(compact)
    _compact_tasks(compact, objects, revisions)
    snapshots = compact.get("priorSnapshots", [])
    for index, snapshot in enumerate(snapshots):
        if is_storage_reference(snapshot):
            validate_storage_reference(snapshot)
            if snapshot["kind"] != SNAPSHOT_KIND:
                raise storage_error("Historical slot requires a snapshot")
            _require_initial_snapshot_context(snapshot["lineage"], compact)
            continue
        if not isinstance(snapshot, dict):
            raise storage_error("Historical snapshot must be an object")
        if snapshot.get("priorSnapshots"):
            raise storage_error("Recursive snapshots are forbidden")
        _require_initial_snapshot_context(_lineage(snapshot), compact)
        _compact_tasks(snapshot, objects, revisions)
        snapshots[index] = _prepare_reference(
            snapshot,
            SNAPSHOT_KIND,
            _lineage(snapshot),
            objects,
        )
    _bounded_bytes(compact, "rootBytes")
    if len(objects) > MAX_REACHABLE_OBJECTS:
        raise capacity_error(
            "reachableObjects",
            len(objects),
            len(objects),
            MAX_REACHABLE_OBJECTS,
        )
    size = sum(map(len, objects.values()))
    if size > MAX_REACHABLE_BYTES:
        raise capacity_error("reachableBytes", size, size, MAX_REACHABLE_BYTES)
    if operation is not None:
        operation.bind(operation.root, compact)
        for name, data in objects.items():
            operation._admit(compact["storage"], name, data)
    return PreparedStorage(compact, objects)


def _require_reference_context(
    reference: dict[str, Any],
    kind: str,
    lineage: dict[str, Any],
) -> None:
    if reference["kind"] != kind or reference["lineage"] != lineage:
        raise storage_error("Immutable reference kind or lineage mismatch")


def _validate_body_kind(body: dict[str, Any], kind: str) -> None:
    if kind == SNAPSHOT_KIND:
        if (
            not isinstance(body.get("tasks"), list)
            or "priorSnapshots" in body
            or body.get("financialRole") != _FINANCIAL_ROLE
        ):
            raise storage_error("Historical snapshot shape or role is invalid")
        if len(body["tasks"]) > MAX_CURRENT_TASKS:
            raise capacity_error(
                "snapshotTasks",
                len(body["tasks"]),
                len(body["tasks"]),
                MAX_CURRENT_TASKS,
            )
    elif body.get("schemaVersion") != _BODY_SCHEMAS[kind]:
        raise storage_error("Immutable body schema does not match its kind")


def _require_initial_snapshot_context(
    lineage: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if is_initial_snapshot_lineage(SNAPSHOT_KIND, lineage) and any(
        lineage[key] != state.get(key) for key in ("runId", "packageId")
    ):
        raise storage_error("Historical run/package lineage mismatch")


def _require_initial_snapshot_body(
    body: dict[str, Any],
    kind: str,
    lineage: dict[str, Any],
) -> None:
    if not is_initial_snapshot_lineage(kind, lineage):
        return
    if body.get("tasks") != [] or any(
        key not in body or type(body[key]) is not type(value) or body[key] != value for key, value in lineage.items()
    ):
        raise storage_error("Initial snapshot body or lineage is invalid")
    _forbid_nested_references(body, set(), forbid_evidence=True)


def _decode_object(
    data: bytes,
    reference: dict[str, Any],
) -> dict[str, Any]:
    body = load_json_object(data, label="immutable workflow object")
    if (
        len(data) != reference["bytes"]
        or canonical_bytes(body) + b"\n" != data
        or sha256_hex(data[:-1]) != reference["sha256"]
    ):
        raise storage_error("Immutable encoding, byte count or SHA mismatch")
    _validate_body_kind(body, reference["kind"])
    _require_initial_snapshot_body(body, reference["kind"], reference["lineage"])
    if item_counts(body) != reference["itemCounts"]:
        raise storage_error("Immutable item counts mismatch")
    for key, value in reference["lineage"].items():
        if key in body and body[key] != value:
            raise storage_error("Immutable body lineage mismatch")
    return body


@dataclass
class _TaskSelection:
    task_id: Any
    attempt: Any
    field: str
    reference: Any
    task: dict[str, Any]
    body: dict[str, Any] | None = None
    matched: bool = False

    def match_absence(self, context: dict[str, Any]) -> None:
        if self.reference is not None:
            return
        for task in context.get("tasks", []):
            for record in _task_records(task):
                selected = {"id": task.get("id"), **record}
                if selected == self.task and self.field not in record:
                    self.matched = True

    def match(
        self,
        reference: Any,
        kind: str,
        lineage: dict[str, Any],
    ) -> None:
        if (
            kind == LEAF_KINDS[self.field]
            and lineage["taskId"] == self.task_id
            and lineage["attempt"] == self.attempt
            and reference == self.reference
        ):
            self.matched = True


class _Graph:
    def __init__(
        self,
        root: Path,
        state: dict[str, Any],
        objects: dict[str, bytes],
        operation: StorageOperation,
        selection: _TaskSelection | None = None,
    ) -> None:
        self.root, self.state, self.objects = root, state, objects
        self.operation = operation
        self.deadline = operation.deadline
        self.initial_reads = operation.physical_reads
        self.reference_digests: set[str] = set()
        self.seen: dict[str, dict[str, Any]] = {}
        self.total_bytes = 0
        self.reads = 0
        self.revisions = _plan_revisions(state)
        self.selection = selection

    def visit(
        self,
        reference: Any,
        kind: str,
        lineage: dict[str, Any],
    ) -> dict[str, Any] | None:
        check_deadline(self.deadline)
        reference = validate_storage_reference(reference)
        _require_reference_context(reference, kind, lineage)
        name = reference["path"]
        self.reference_digests.add(canonical_digest(reference))
        prior = self.seen.get(name)
        if prior is not None:
            # Same canonical object can occupy repeated unambiguous slots.
            for key in ("kind", "sha256", "bytes", "itemCounts"):
                if prior[key] != reference[key]:
                    raise storage_error("Ambiguous duplicate reference")
            for key, value in prior["bodyLineage"].items():
                if reference["lineage"][key] != value:
                    raise storage_error("Duplicate body lineage mismatch")
            return None
        count = len(self.seen) + 1
        size = self.total_bytes + reference["bytes"]
        if count > MAX_REACHABLE_OBJECTS:
            raise capacity_error(
                "reachableObjects",
                len(self.seen),
                count,
                MAX_REACHABLE_OBJECTS,
            )
        if size > MAX_REACHABLE_BYTES:
            raise capacity_error(
                "reachableBytes",
                self.total_bytes,
                size,
                MAX_REACHABLE_BYTES,
            )
        data = self.objects.get(name)
        if data is None:
            data = read_object(
                self.root,
                self.state["storage"],
                name,
                self.deadline,
                operation=self.operation,
            )
            self.reads += 1
        cached = self.operation._admit(
            self.state["storage"],
            name,
            data,
            kind=kind,
        )
        if cached.verified is not None:
            _require_cached_header(cached.verified, reference)
            self.seen[name] = cached.verified
            self.total_bytes = size
            return None
        body = _decode_object(data, reference)
        if kind != SNAPSHOT_KIND:
            _forbid_nested_references(body, set())
        if self.selection is not None:
            selected = self.selection.reference
            if isinstance(selected, dict) and selected.get("path") == name:
                self.selection.body = body
        keys = reference["lineage"]
        body_lineage = {key: body[key] for key in keys if key in body}
        self.seen[name] = {
            **reference,
            "bodyLineage": body_lineage,
        }
        if kind != SNAPSHOT_KIND:
            cached.verified = deepcopy(self.seen[name])
        self.total_bytes = size
        return body

    def task_leaves(self, context: dict[str, Any]) -> set[int]:
        allowed: set[int] = set()
        if self.selection is not None:
            self.selection.match_absence(context)
        for record, field, kind, lineage in _task_slots(
            context,
            self.revisions,
        ):
            reference = record[field]
            body = self.visit(reference, kind, lineage)
            if self.selection is not None:
                self.selection.match(reference, kind, lineage)
            allowed.add(id(reference))
            if body is not None:
                _forbid_nested_references(body, set())
        return allowed


def _inspect_storage(
    root: Path,
    state: dict[str, Any],
    *,
    prepared: PreparedStorage | None = None,
    operation: StorageOperation,
    selection: _TaskSelection | None = None,
) -> tuple[StorageValidation, _Graph]:
    """Validate all contextual slots, reusing only operation-checked bytes."""
    started = time.monotonic()
    deadline = operation.deadline
    operation.bind(root, state)
    if state.get("schemaVersion") != WORKFLOW_STATE_V5:
        raise storage_error("Reference storage requires workflow state v5")
    validate_storage_metadata(state.get("storage"))
    validate_storage_counts(state)
    _bounded_bytes(state, "rootBytes")
    objects = prepared.objects if prepared is not None else {}
    graph = _Graph(root, state, objects, operation, selection)
    allowed = graph.task_leaves(state)
    identities: set[str] = set()
    for reference in state.get("priorSnapshots", []):
        validate_storage_reference(reference)
        lineage = reference["lineage"]
        for key in ("runId", "packageId"):
            if lineage[key] != state.get(key):
                raise storage_error("Historical run/package lineage mismatch")
        identity = canonical_digest(lineage)
        if identity in identities:
            raise storage_error("Duplicate ambiguous snapshot slot")
        identities.add(identity)
        snapshot = graph.visit(reference, SNAPSHOT_KIND, lineage)
        allowed.add(id(reference))
        if snapshot is not None:
            snapshot_allowed = graph.task_leaves(snapshot)
            _forbid_nested_references(snapshot, snapshot_allowed)
    _forbid_nested_references(state, allowed)
    retained = retained_bytes(root, state["storage"], deadline)
    warnings = tuple(
        category
        for category, actual, limit in (
            (
                "rootBytes",
                len(canonical_bytes(state)) + 1,
                MAX_JSON_INPUT_BYTES,
            ),
            ("reachableObjects", len(graph.seen), MAX_REACHABLE_OBJECTS),
            ("reachableBytes", graph.total_bytes, MAX_REACHABLE_BYTES),
            ("retainedBytes", retained, MAX_RETAINED_BYTES),
            ("tasks", len(state.get("tasks", [])), MAX_CURRENT_TASKS),
            (
                "priorSnapshots",
                len(state.get("priorSnapshots", [])),
                MAX_SNAPSHOTS,
            ),
            (
                "operationLedger",
                len(state.get("operationLedger", {})),
                MAX_OPERATIONS,
            ),
        )
        if actual * 4 >= limit * 3
    )
    check_deadline(deadline)
    operation._graph_checked(state)
    return StorageValidation(
        len(graph.seen),
        graph.total_bytes,
        retained,
        operation.physical_reads - graph.initial_reads,
        time.monotonic() - started,
        warnings,
    ), graph


def validate_storage(
    root: Path,
    state: dict[str, Any],
    *,
    prepared: PreparedStorage | None = None,
    deadline: float | None = None,
    operation: StorageOperation | None = None,
) -> StorageValidation:
    with storage_operation(
        root,
        state,
        operation,
        deadline=deadline,
    ) as current:
        return _inspect_storage(
            root,
            state,
            prepared=prepared,
            operation=current,
        )[0]


def _require_cached_header(
    cached: dict[str, Any],
    reference: dict[str, Any],
) -> None:
    for key in ("kind", "sha256", "bytes", "itemCounts"):
        if cached[key] != reference[key]:
            raise storage_error("Cached immutable header mismatch")
    for key, value in cached["bodyLineage"].items():
        if reference["lineage"][key] != value:
            raise storage_error("Cached immutable body lineage mismatch")


def _prepared_write_digest(
    prepared: PreparedStorage,
    operation: StorageOperation,
) -> str:
    for name, data in prepared.objects.items():
        operation.check()
        if not isinstance(data, bytes):
            raise storage_error("Prepared writes require exact immutable bytes")
        if len(data) > MAX_JSON_INPUT_BYTES:
            raise capacity_error(
                "objectBytes",
                len(data),
                len(data),
                MAX_JSON_INPUT_BYTES,
            )
        operation._admit(prepared.state["storage"], name, data)
    reachable = _referenced_names(prepared.state)
    pending, visited = list(reachable), set()
    while pending:
        operation.check()
        name = pending.pop()
        if name in visited or name not in prepared.objects:
            continue
        visited.add(name)
        children = _referenced_names(load_json_object(prepared.objects[name]))
        reachable.update(children)
        pending.extend(children)
    for name, data in prepared.objects.items():
        operation.check()
        if not isinstance(data, bytes):
            raise storage_error("Prepared writes require exact immutable bytes")
        digest = sha256_hex(data[:-1])
        if name != f"objects/{digest}.json":
            raise storage_error("Prepared object path does not match bytes")
        if canonical_bytes(load_json_object(data)) + b"\n" != data:
            raise storage_error("Prepared object is not canonical")
    if not set(prepared.objects).issubset(reachable):
        raise storage_error("Prepared writes contain unreachable objects")
    return write_set_digest(prepared.objects)


def preflight_storage(
    root: Path,
    prepared: PreparedStorage,
    *,
    operation: StorageOperation | None = None,
    allowed_writes: set[Path] | None = None,
) -> CheckedStorageWrites:
    current, owned = choose_operation(root, operation)
    try:
        current.bind(root, prepared.state)
        write_digest = _prepared_write_digest(prepared, current)
        _inspect_storage(
            root,
            prepared.state,
            prepared=prepared,
            operation=current,
        )
        outputs = set(prepared.writes(root, operation=current))
        if allowed_writes is not None and not outputs.issubset(
            {path.absolute() for path in allowed_writes},
        ):
            raise storage_error(
                "Prepared storage exceeds allowed output footprint",
            )
        frontier, missing = preflight_objects(
            root,
            prepared.state["storage"],
            prepared.objects,
            current,
        )
        return current._issue(
            state_digest=canonical_digest(prepared.state),
            write_digest=write_digest,
            storage_root=prepared.state["storage"]["root"],
            frontier=frontier.digest,
            missing=missing,
            standalone=owned,
        )
    except BaseException:
        if owned:
            current.close()
        raise


def persist_storage(
    root: Path,
    prepared: PreparedStorage,
    *,
    operation: StorageOperation | None = None,
    checked: CheckedStorageWrites | None = None,
) -> None:
    supplied = operation or (checked.operation if checked else None)
    current, owned = choose_operation(root, supplied)
    owned |= operation is None and checked is not None and checked.standalone
    try:
        current.bind(root, prepared.state)
        if checked is None:
            checked = preflight_storage(root, prepared, operation=current)
        if (
            checked.operation is not current
            or checked.root != current.root
            or checked.state_digest != canonical_digest(prepared.state)
            or checked.write_digest != _prepared_write_digest(prepared, current)
            or checked.storage_root != prepared.state["storage"]["root"]
        ):
            raise storage_error(
                "Checked storage context/root/state/write-set changed",
            )
        persist_objects(
            root,
            prepared.state["storage"],
            prepared.objects,
            operation=current,
            checked=checked,
        )
    finally:
        if owned:
            current.close()


def _referenced_names(value: Any) -> set[str]:
    result: set[str] = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if is_storage_reference(item):
            result.add(validate_storage_reference(item)["path"])
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return result


def load_object(
    root: Path,
    state: dict[str, Any],
    reference: dict[str, Any],
    *,
    operation: StorageOperation | None = None,
) -> dict[str, Any]:
    """Load only a reference selected from a freshly checked complete graph."""
    with storage_operation(root, state, operation) as current:
        _, graph = _inspect_storage(root, state, operation=current)
        validate_storage_reference(reference)
        if canonical_digest(reference) not in graph.reference_digests:
            raise storage_error(
                "Selected reference is outside the checked graph",
            )
        return _decode_object(
            read_object(
                root,
                state["storage"],
                reference["path"],
                current.deadline,
                operation=current,
            ),
            reference,
        )


def iter_historical_snapshots(
    root: Path,
    state: dict[str, Any],
    *,
    operation: StorageOperation | None = None,
) -> Iterator[dict[str, Any]]:
    with storage_operation(root, state, operation) as current:
        if state.get("schemaVersion") != WORKFLOW_STATE_V5:
            yield from state.get("priorSnapshots", [])
            return
        _inspect_storage(root, state, operation=current)
        for reference in state.get("priorSnapshots", []):
            current.check()
            yield _decode_object(
                read_object(
                    root,
                    state["storage"],
                    reference["path"],
                    current.deadline,
                    operation=current,
                ),
                reference,
            )


def task_evidence(
    root: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    field: str,
    *,
    operation: StorageOperation | None = None,
) -> dict[str, Any] | None:
    if field not in LEAF_KINDS:
        raise storage_error("Unsupported task evidence slot")
    with storage_operation(root, state, operation) as current:
        value = task.get(field)
        if state.get("schemaVersion") != WORKFLOW_STATE_V5:
            if value is None:
                return None
            if not isinstance(value, dict) or is_storage_reference(value):
                raise storage_error("Legacy task evidence requires inline data")
            return value
        selection = _TaskSelection(
            task.get("id"),
            task.get("attempt", 0),
            field,
            value,
            task,
        )
        _inspect_storage(root, state, operation=current, selection=selection)
        if not selection.matched:
            raise storage_error("Selected reference does not match task slot")
        if value is None:
            return None
        if not is_storage_reference(value):
            raise storage_error("V5 immutable evidence requires a reference")
        return _decode_object(
            read_object(
                root,
                state["storage"],
                value["path"],
                current.deadline,
                operation=current,
            ),
            value,
        )
