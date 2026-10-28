"""Operation-scoped lower storage composition, never native task acceptance."""

from __future__ import annotations

import ast
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts import workflow_storage_io as storage_io
from agent_lifecycle.contracts import workflow_storage_schemas as schemas
from agent_lifecycle.contracts.workflow_storage import (
    iter_historical_snapshots,
    load_object,
    persist_storage,
    preflight_storage,
    prepare_storage,
    task_evidence,
    validate_storage,
)
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from tests.workflow.test_state_storage import (
    initial_snapshot_fixture,
    snapshot_object,
    state_fixture,
)

_CONTEXT = "agent_lifecycle.contracts.workflow_storage_context"


class StorageOperationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self):
        prepared = prepare_storage(state_fixture(), storage_root="store")
        persist_storage(self.root, prepared)
        return prepared

    def prospective(self, current, operation):
        state = deepcopy(current.state)
        state["tasks"][0]["resultChangeSetEvidence"] = {
            "schemaVersion": "agent-task-change-set-evidence.v1",
            "entries": [{"new": True}],
        }
        return prepare_storage(state, operation=operation)

    def test_initial_snapshot_cache_reuse_checks_every_contextual_header(self):
        prepared = prepare_storage(
            initial_snapshot_fixture(),
            storage_root="store",
        )
        persist_storage(self.root, prepared)
        with StorageOperation(self.root) as operation:
            validate_storage(self.root, prepared.state, operation=operation)
            reads = operation.physical_reads
            reference = prepared.state["priorSnapshots"][0]
            original = initial_snapshot_fixture()["priorSnapshots"][0]
            self.assertEqual(
                load_object(
                    self.root,
                    prepared.state,
                    reference,
                    operation=operation,
                ),
                original,
            )
            snapshots = list(
                iter_historical_snapshots(
                    self.root,
                    prepared.state,
                    operation=operation,
                )
            )
            self.assertEqual(snapshots[0], original)
            self.assertEqual(operation.physical_reads, reads)
            for variant in ("bound", "count", "run", "bool"):
                changed = deepcopy(prepared.state)
                reference = changed["priorSnapshots"][0]
                if variant == "bound":
                    reference["lineage"].update(
                        planDigest="9" * 64,
                        sourceRevision="source",
                    )
                elif variant == "count":
                    reference["itemCounts"]["tasks"] = 1
                elif variant == "run":
                    reference["lineage"]["runId"] = "OTHER"
                else:
                    reference["lineage"]["planRevision"] = False
                with (
                    self.subTest(variant=variant),
                    self.assertRaises(LifecycleError),
                ):
                    validate_storage(
                        self.root,
                        changed,
                        operation=operation,
                    )
            self.assertEqual(operation.physical_reads, reads)
            self.assertEqual(operation.publications, ())

    def test_damaged_unselected_initial_body_blocks_readers_and_publication(self):
        prepared = prepare_storage(
            initial_snapshot_fixture(),
            storage_root="store",
        )
        persist_storage(self.root, prepared)
        initial = prepared.state["priorSnapshots"][0]
        original = initial_snapshot_fixture()["priorSnapshots"][0]
        for variant in ("missing", "bool", "tasks", "hidden-reference"):
            body = deepcopy(original)
            if variant == "missing":
                body.pop("sourceRevision")
            elif variant == "bool":
                body["planRevision"] = False
            elif variant == "tasks":
                body["tasks"] = [{"id": "hidden-task"}]
            else:
                body["hidden"] = [prepared.state["tasks"][0]["ownershipReceipt"]]
            reference, data = snapshot_object(body, initial["lineage"])
            changed = deepcopy(prepared.state)
            changed["priorSnapshots"][0] = reference
            (self.root / "store" / reference["path"]).write_bytes(data)
            before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
            task = changed["tasks"][0]
            for reader in ("task", "object", "history", "persist"):
                with (
                    self.subTest(variant=variant, reader=reader),
                    self.assertRaises(LifecycleError),
                ):
                    if reader == "task":
                        task_evidence(
                            self.root,
                            changed,
                            task,
                            "ownershipReceipt",
                        )
                    elif reader == "object":
                        load_object(
                            self.root,
                            changed,
                            task["ownershipReceipt"],
                        )
                    elif reader == "history":
                        list(iter_historical_snapshots(self.root, changed))
                    else:
                        persist_storage(self.root, prepare_storage(changed))
                self.assertEqual(
                    {p: p.read_bytes() for p in self.root.rglob("*.json")},
                    before,
                )

    def test_all_entrypoints_share_one_physical_read_per_distinct_object(self):
        initial = self.fixture()
        with (
            StorageOperation(
                self.root,
                state_path=self.root / "run.state.json",
                run_id="run",
            ) as operation,
            patch.object(
                storage_io,
                "read_authority_bytes",
                wraps=storage_io.read_authority_bytes,
            ) as physical,
        ):
            state = initial.state
            report = validate_storage(self.root, state, operation=operation)
            reference = state["tasks"][0]["ownershipReceipt"]
            body = load_object(self.root, state, reference, operation=operation)
            self.assertEqual(body["taskId"], "T")
            selected = task_evidence(
                self.root,
                state,
                state["tasks"][0],
                "ownershipReceipt",
                operation=operation,
            )
            self.assertEqual(selected, body)
            snapshots = list(
                iter_historical_snapshots(
                    self.root,
                    state,
                    operation=operation,
                )
            )
            self.assertEqual(len(snapshots), 1)
            same = prepare_storage(
                state_fixture(),
                storage_root="store",
                operation=operation,
            )
            checked = preflight_storage(self.root, same, operation=operation)
            persist_storage(
                self.root,
                same,
                operation=operation,
                checked=checked,
            )
            self.assertEqual(physical.call_count, report.object_count)
            self.assertEqual(operation.physical_reads, 3)
            self.assertEqual(
                operation.physical_read_bytes,
                report.reachable_bytes,
            )
            self.assertEqual(operation.object_bytes, report.reachable_bytes)
            self.assertEqual(operation.publications, ())
            self.assertTrue(operation.checked_graphs)

    def test_prepared_bytes_load_after_persist_without_disk_reads(self):
        with StorageOperation(self.root) as operation:
            prepared = prepare_storage(
                state_fixture(),
                storage_root="store",
                operation=operation,
            )
            validate_storage(
                self.root,
                prepared.state,
                prepared=prepared,
                operation=operation,
            )
            checked = preflight_storage(
                self.root,
                prepared,
                operation=operation,
            )
            self.assertFalse((self.root / "store").exists())
            persist_storage(
                self.root,
                prepared,
                operation=operation,
                checked=checked,
            )
            selected = prepared.state["tasks"][0]
            task_evidence(
                self.root,
                prepared.state,
                selected,
                "ownershipReceipt",
                operation=operation,
            )
            self.assertEqual(operation.physical_reads, 0)
            self.assertEqual(len(operation.publications), 3)
            self.assertEqual(operation.object_count, 3)

    def test_ambient_context_is_reused_and_cannot_be_silently_replaced(self):
        initial = self.fixture()
        with StorageOperation(self.root) as operation:
            started, deadline = operation.started, operation.deadline
            validate_storage(self.root, initial.state)
            list(iter_historical_snapshots(self.root, initial.state))
            task_evidence(
                self.root,
                initial.state,
                initial.state["tasks"][0],
                "ownershipReceipt",
            )
            prepared = prepare_storage(state_fixture(), storage_root="store")
            checked = preflight_storage(self.root, prepared)
            self.assertIs(checked.operation, operation)
            persist_storage(self.root, prepared, checked=checked)
            self.assertEqual(operation.physical_reads, 3)
            self.assertEqual(operation.started, started)
            self.assertEqual(operation.deadline, deadline)
            foreign = StorageOperation(self.root)
            with self.assertRaises(LifecycleError):
                validate_storage(self.root, initial.state, operation=foreign)
            with self.assertRaises(LifecycleError), foreign:
                self.fail("Foreign context replaced active operation")
            foreign.close()
        self.assertIsNone(StorageOperation.current())

    def test_new_operation_refreshes_trust_and_observed_identity(self):
        initial = self.fixture()
        first = StorageOperation(self.root)
        validate_storage(self.root, initial.state, operation=first)
        path = next(iter(initial.writes(self.root)))
        path.write_bytes(b"{}\n")
        with self.assertRaises(LifecycleError):
            validate_storage(self.root, initial.state, operation=first)
        with StorageOperation(self.root) as second:
            with self.assertRaises(LifecycleError):
                validate_storage(self.root, initial.state, operation=second)
            self.assertGreater(second.physical_reads, 0)
        first.close()
        with self.assertRaises(LifecycleError):
            validate_storage(self.root, initial.state, operation=first)

    def test_external_values_cannot_mutate_cached_trust(self):
        initial = self.fixture()
        with StorageOperation(self.root) as operation:
            validate_storage(self.root, initial.state, operation=operation)
            state = deepcopy(initial.state)
            state["tasks"][0]["ownershipReceipt"]["itemCounts"]["entries"] += 1
            with self.assertRaises(LifecycleError):
                validate_storage(self.root, state, operation=operation)
            reference = initial.state["tasks"][0]["ownershipReceipt"]
            body = load_object(
                self.root,
                initial.state,
                reference,
                operation=operation,
            )
            body["entries"].clear()
            original = load_object(
                self.root,
                initial.state,
                reference,
                operation=operation,
            )
            self.assertEqual(len(original["entries"]), 1)

    def test_cached_slots_still_check_kind_task_attempt_and_plan_context(self):
        initial = self.fixture()
        with StorageOperation(self.root) as operation:
            validate_storage(self.root, initial.state, operation=operation)
            for variant in ("kind", "task", "attempt", "plan"):
                task = deepcopy(initial.state["tasks"][0])
                if variant == "kind":
                    task["ownershipReceipt"] = task["resultChangeSetEvidence"]
                elif variant == "task":
                    task["id"] = "OTHER"
                elif variant == "attempt":
                    task["attempt"] = 99
                else:
                    task["ownershipReceipt"]["lineage"]["planRevision"] = 999
                with (
                    self.subTest(variant=variant),
                    self.assertRaises(
                        LifecycleError,
                    ),
                ):
                    task_evidence(
                        self.root,
                        initial.state,
                        task,
                        "ownershipReceipt",
                        operation=operation,
                    )
            state = deepcopy(initial.state)
            receipt = state["tasks"][0]["ownershipReceipt"]
            receipt["lineage"]["planRevision"] = 999
            with self.assertRaises(LifecycleError):
                validate_storage(self.root, state, operation=operation)

    def test_operation_budgets_include_prior_and_prepared_graphs_together(self):
        initial = self.fixture()
        for limit in ("objects", "bytes"):
            with (
                self.subTest(limit=limit),
                StorageOperation(
                    self.root,
                ) as operation,
            ):
                validate_storage(self.root, initial.state, operation=operation)
                name = "MAX_REACHABLE_BYTES"
                if limit == "objects":
                    name = "MAX_REACHABLE_OBJECTS"
                value = 3 if limit == "objects" else operation.object_bytes + 1
                with (
                    patch(
                        _CONTEXT + "." + name,
                        value,
                    ),
                    self.assertRaises(LifecycleError) as caught,
                ):
                    self.prospective(initial, operation)
                self.assertEqual(
                    caught.exception.code,
                    ("workflow-storage-capacity-exceeded"),
                )
                self.assertEqual(operation.publications, ())

    def test_root_run_path_and_closed_context_bindings(self):
        initial = self.fixture()
        with StorageOperation(self.root, run_id="run") as operation:
            validate_storage(self.root, initial.state, operation=operation)
            operation.bind_path(self.root / "one.json")
            with self.assertRaises(LifecycleError):
                operation.bind_path(self.root / "two.json")
            with self.assertRaises(LifecycleError):
                validate_storage(
                    self.root / "other",
                    initial.state,
                    operation=operation,
                )
            for key, value in (
                ("runId", "another"),
                (
                    "storage",
                    {
                        "schemaVersion": "agent-workflow-storage.v1",
                        "root": "other",
                    },
                ),
            ):
                state = {**initial.state, key: value}
                with self.assertRaises(LifecycleError):
                    validate_storage(self.root, state, operation=operation)
        with self.assertRaises(LifecycleError):
            validate_storage(self.root, initial.state, operation=operation)

    def test_one_start_and_external_deadlines_only_tighten(self):
        initial = self.fixture()
        clock = {"now": 100.0}
        with patch(
            "agent_lifecycle.contracts.workflow_storage_context.time.monotonic",
            side_effect=lambda: clock["now"],
        ):
            with StorageOperation(self.root, deadline=999.0) as operation:
                self.assertEqual(operation.started, 100.0)
                self.assertEqual(operation.deadline, 130.0)
                validate_storage(self.root, initial.state, operation=operation)
                clock["now"] = 120.0
                validate_storage(
                    self.root,
                    initial.state,
                    operation=operation,
                    deadline=125.0,
                )
                self.assertEqual(operation.started, 100.0)
                self.assertEqual(operation.deadline, 125.0)
                with self.assertRaises(LifecycleError):
                    validate_storage(
                        self.root,
                        initial.state,
                        operation=operation,
                        deadline=130.0,
                    )
                clock["now"] = 125.0
                with self.assertRaises(LifecycleError):
                    list(
                        iter_historical_snapshots(
                            self.root,
                            initial.state,
                            operation=operation,
                        )
                    )
            shorter = StorageOperation(self.root, deadline=110.0)
            self.assertEqual(shorter.deadline, 110.0)
            shorter.close()

    def test_nonfinite_nested_deadlines_preserve_finite_expiry(self):
        initial = self.fixture()
        state_path = self.root / "run.state.json"
        state_path.write_bytes(b"unchanged fixture authority")
        for invalid in (float("nan"), float("inf"), float("-inf")):
            for route in ("explicit", "ambient", "reader"):
                clock = {"now": 100.0}
                with (
                    self.subTest(deadline=repr(invalid), route=route),
                    patch(
                        _CONTEXT + ".time.monotonic",
                        side_effect=lambda observed=clock: observed["now"],
                    ),
                    StorageOperation(self.root, state_path=state_path) as op,
                ):
                    pending = prepare_storage(initial.state, operation=op)
                    checked = preflight_storage(
                        self.root,
                        pending,
                        operation=op,
                    )
                    before = self.operation_observation(op)
                    with self.assertRaises(LifecycleError) as caught:
                        if route == "reader":
                            reference = initial.state["priorSnapshots"][0]
                            storage_io.read_object(
                                self.root,
                                initial.state["storage"],
                                reference["path"],
                                invalid,
                                operation=op,
                            )
                        else:
                            validate_storage(
                                self.root,
                                initial.state,
                                deadline=invalid,
                                operation=op if route == "explicit" else None,
                            )
                    self.assertEqual(
                        caught.exception.code,
                        ("workflow-storage-deadline-invalid"),
                    )
                    self.assertEqual(self.operation_observation(op), before)
                    # A rejected deadline must not consume or poison the token.
                    persist_storage(
                        self.root,
                        pending,
                        operation=op,
                        checked=checked,
                    )
                    expiry_checked = preflight_storage(
                        self.root,
                        pending,
                        operation=op,
                    )
                    clock["now"] = before[1]
                    with self.assertRaises(LifecycleError) as expired:
                        persist_storage(
                            self.root,
                            pending,
                            operation=op,
                            checked=expiry_checked,
                        )
                    self.assertEqual(
                        expired.exception.code,
                        ("workflow-storage-deadline-exceeded"),
                    )
                    self.assertEqual(op.publications, ())
                    self.assertEqual(
                        state_path.read_bytes(),
                        (b"unchanged fixture authority"),
                    )

    @staticmethod
    def operation_observation(operation):
        return (
            operation.started,
            operation.deadline,
            operation.object_count,
            operation.object_bytes,
            operation.physical_reads,
            operation.physical_read_bytes,
            operation.checked_graphs,
            operation.binding_digest,
            operation.publications,
        )

    def test_nonfinite_constructor_and_raw_io_deadlines_refuse_before_io(self):
        metadata = {
            "schemaVersion": "agent-workflow-storage.v1",
            "root": "store",
        }
        for invalid in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(deadline=repr(invalid)):
                with self.assertRaises(LifecycleError) as caught:
                    StorageOperation(self.root, deadline=invalid)
                self.assertEqual(
                    caught.exception.code,
                    ("workflow-storage-deadline-invalid"),
                )
                calls = (
                    lambda deadline=invalid: storage_io.check_deadline(
                        deadline,
                    ),
                    lambda deadline=invalid: storage_io.storage_frontier(
                        self.root,
                        metadata,
                        deadline,
                    ),
                    lambda deadline=invalid: storage_io.retained_bytes(
                        self.root,
                        metadata,
                        deadline,
                    ),
                    lambda deadline=invalid: storage_io.observe_object(
                        self.root,
                        metadata,
                        "objects/" + "a" * 64 + ".json",
                        deadline,
                    ),
                    lambda deadline=invalid: storage_io.read_object(
                        self.root,
                        metadata,
                        "objects/" + "a" * 64 + ".json",
                        deadline,
                    ),
                )
                with patch.object(storage_io, "hold_authority_directory") as io:
                    for call in calls:
                        with self.assertRaises(LifecycleError) as raw:
                            call()
                        self.assertEqual(
                            raw.exception.code,
                            ("workflow-storage-deadline-invalid"),
                        )
                    io.assert_not_called()

    def test_preflight_refuses_old_history_damage_and_collisions(self):
        for variant in ("missing-history", "tampered-history", "collision"):
            with (
                self.subTest(
                    variant=variant,
                ),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                initial = prepare_storage(state_fixture(), storage_root="store")
                persist_storage(root, initial)
                if variant == "collision":
                    path = next(iter(initial.writes(root)))
                    path.write_bytes(b"wrong\n")
                    prospective = prepare_storage(
                        state_fixture(),
                        storage_root="store",
                    )
                else:
                    reference = initial.state["priorSnapshots"][0]
                    path = root / "store" / reference["path"]
                    if variant == "missing-history":
                        path.unlink()
                    else:
                        path.write_bytes(b"{}\n")
                    prospective = prepare_storage(initial.state)
                before = {p.name for p in (root / "store/objects").iterdir()}
                with patch.object(
                    storage_io,
                    "create_authority_bytes",
                ) as create:
                    with self.assertRaises(LifecycleError):
                        preflight_storage(root, prospective)
                    create.assert_not_called()
                self.assertEqual(
                    before,
                    {p.name for p in (root / "store/objects").iterdir()},
                )

    def test_preflight_quota_and_footprint_before_publication(self):
        prepared = prepare_storage(state_fixture(), storage_root="store")
        with self.assertRaises(LifecycleError):
            preflight_storage(self.root, prepared, allowed_writes=set())
        self.assertFalse((self.root / "store").exists())
        directory = self.root / "store/objects"
        directory.mkdir(parents=True)
        with (directory / "orphan").open("wb") as handle:
            handle.truncate(schemas.MAX_RETAINED_BYTES)
        with self.assertRaises(LifecycleError) as caught:
            preflight_storage(self.root, prepared)
        self.assertEqual(caught.exception.details["category"], "retainedBytes")
        self.assertEqual({p.name for p in directory.iterdir()}, {"orphan"})

    def test_capability_binds_state_map_root_context_and_identity(self):
        for variant in ("state", "map", "root", "context", "forged"):
            with (
                self.subTest(
                    variant=variant,
                ),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                operation = StorageOperation(root)
                prepared = prepare_storage(
                    state_fixture(),
                    storage_root="store",
                    operation=operation,
                )
                checked = preflight_storage(root, prepared, operation=operation)
                selected_root, selected_context = root, operation
                if variant == "state":
                    prepared.state["padding"] = "changed"
                elif variant == "map":
                    prepared.objects.pop(next(iter(prepared.objects)))
                elif variant == "root":
                    selected_root = root / "different"
                elif variant == "context":
                    selected_context = StorageOperation(root)
                else:
                    checked = replace(checked)
                with self.assertRaises(LifecycleError):
                    persist_storage(
                        selected_root,
                        prepared,
                        operation=selected_context,
                        checked=checked,
                    )
                self.assertFalse((root / "store").exists())
                operation.close()
                selected_context.close()

    def test_checked_capability_rejects_changed_or_replaced_frontier(self):
        initial = self.fixture()
        for variant in ("new-orphan", "replacement"):
            with (
                self.subTest(
                    variant=variant,
                ),
                StorageOperation(self.root) as operation,
            ):
                prospective = self.prospective(initial, operation)
                checked = preflight_storage(
                    self.root,
                    prospective,
                    operation=operation,
                )
                if variant == "new-orphan":
                    (self.root / "store/objects/orphan").write_bytes(b"x")
                else:
                    path = next(iter(initial.writes(self.root)))
                    replacement = self.root / "replacement"
                    replacement.write_bytes(path.read_bytes())
                    replacement.replace(path)
                with patch.object(
                    storage_io,
                    "create_authority_bytes",
                ) as create:
                    with self.assertRaises(LifecycleError):
                        persist_storage(
                            self.root,
                            prospective,
                            operation=operation,
                            checked=checked,
                        )
                    create.assert_not_called()
                for path in prospective.writes(self.root):
                    self.assertFalse(path.exists())

    def test_same_byte_orphan_retry_with_standalone_capability(self):
        prepared = prepare_storage(state_fixture(), storage_root="store")
        name, data = next(iter(prepared.objects.items()))
        path = self.root / "store" / name
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        checked = preflight_storage(self.root, prepared)
        self.assertEqual(checked.operation.physical_reads, 1)
        persist_storage(self.root, prepared, checked=checked)
        identities = {
            p: (p.stat().st_ino, p.read_bytes())
            for p in prepared.writes(
                self.root,
            )
        }
        persist_storage(self.root, prepared)
        outputs = prepared.writes(self.root)
        self.assertEqual(
            identities,
            {p: (p.stat().st_ino, p.read_bytes()) for p in outputs},
        )
        with self.assertRaises(LifecycleError):
            persist_storage(self.root, prepared, checked=checked)

    def test_low_level_persistence_cannot_bypass_checked_footprint(self):
        for variant in ("root", "bytes", "mutable-bytes"):
            with (
                self.subTest(variant=variant),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                with StorageOperation(root) as operation:
                    prepared = prepare_storage(
                        state_fixture(),
                        storage_root="store",
                        operation=operation,
                    )
                    checked = preflight_storage(
                        root,
                        prepared,
                        operation=operation,
                    )
                    selected = root
                    if variant == "root":
                        selected = root / "other"
                    else:
                        name = next(iter(prepared.objects))
                        data = prepared.objects[name]
                        prepared.objects[name] = (
                            data + b" "
                            if variant == "bytes"
                            else bytearray(
                                data,
                            )
                        )
                    with self.assertRaises(LifecycleError):
                        storage_io.persist_objects(
                            selected,
                            prepared.state["storage"],
                            prepared.objects,
                            operation=operation,
                            checked=checked,
                        )
                    self.assertFalse((root / "store").exists())
                    self.assertFalse((root / "other").exists())

    def test_capability_refuses_late_first_state_path_binding(self):
        with StorageOperation(self.root) as operation:
            prepared = prepare_storage(
                state_fixture(),
                storage_root="store",
                operation=operation,
            )
            checked = preflight_storage(
                self.root,
                prepared,
                operation=operation,
            )
            operation.bind_path(self.root / "bound-after-preflight.json")
            with self.assertRaises(LifecycleError):
                persist_storage(
                    self.root,
                    prepared,
                    operation=operation,
                    checked=checked,
                )
            self.assertFalse((self.root / "store").exists())

    def test_raw_storage_reader_rejects_path_aliases(self):
        initial = self.fixture()
        names = (
            "../outside.json",
            "objects/../outside.json",
            str(self.root / "outside.json"),
            "objects/CON.json",
        )
        for name in names:
            with (
                self.subTest(name=name),
                StorageOperation(self.root) as operation,
                patch.object(storage_io, "read_authority_bytes") as physical,
            ):
                with self.assertRaises(LifecycleError):
                    storage_io.read_object(
                        self.root,
                        initial.state["storage"],
                        name,
                        operation.deadline,
                        operation=operation,
                    )
                physical.assert_not_called()

    def test_expiry_before_publication_preserves_authority(self):
        clock = {"now": 100.0}
        state_path = self.root / "run.state.json"
        event_path = self.root / "events.jsonl"
        state_path.write_bytes(b"original state")
        event_path.write_bytes(b"original events")
        with (
            patch(
                _CONTEXT + ".time.monotonic",
                side_effect=lambda: clock["now"],
            ),
            StorageOperation(self.root, state_path=state_path) as operation,
        ):
            prepared = prepare_storage(
                state_fixture(),
                storage_root="store",
                operation=operation,
            )
            checked = preflight_storage(
                self.root,
                prepared,
                operation=operation,
            )
            clock["now"] = 130.0
            with self.assertRaises(LifecycleError):
                persist_storage(
                    self.root,
                    prepared,
                    operation=operation,
                    checked=checked,
                )
            self.assertEqual(operation.publications, ())
            self.assertFalse((self.root / "store").exists())
        self.assertEqual(state_path.read_bytes(), b"original state")
        self.assertEqual(event_path.read_bytes(), b"original events")

    def test_expiry_after_publication_preserves_factual_bytes(self):
        for stop_after in (1, 3):
            with (
                self.subTest(
                    stop_after=stop_after,
                ),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                clock = {"now": 100.0}
                real_create = storage_io.create_authority_bytes
                completed = 0

                def create(
                    *args,
                    observed_clock=clock,
                    observer=real_create,
                    stop=stop_after,
                    **kwargs,
                ):
                    nonlocal completed
                    result = observer(*args, **kwargs)
                    completed += 1
                    if completed == stop:
                        observed_clock["now"] = 131.0
                    return result

                with (
                    patch(
                        _CONTEXT + ".time.monotonic",
                        side_effect=lambda observed=clock: observed["now"],
                    ),
                    StorageOperation(root) as operation,
                ):
                    prepared = prepare_storage(
                        state_fixture(),
                        storage_root="store",
                        operation=operation,
                    )
                    checked = preflight_storage(
                        root,
                        prepared,
                        operation=operation,
                    )
                    with (
                        patch.object(
                            storage_io,
                            "create_authority_bytes",
                            create,
                        ),
                        self.assertRaises(LifecycleError) as caught,
                    ):
                        persist_storage(
                            root,
                            prepared,
                            operation=operation,
                            checked=checked,
                        )
                    self.assertEqual(
                        caught.exception.code,
                        ("workflow-storage-deadline-exceeded"),
                    )
                    self.assertEqual(len(operation.publications), stop_after)
                    self.assertEqual(
                        len(list((root / "store/objects").iterdir())),
                        stop_after,
                    )
                    for path, data in prepared.writes(root).items():
                        if path.exists():
                            self.assertEqual(path.read_bytes(), data)
                    self.assertEqual(operation.elapsed_seconds, 31.0)

    def test_lower_service_has_no_reverse_or_future_dependency(self):
        root = Path(__file__).resolve().parents[2] / "src/agent_lifecycle"
        modules = (
            "workflow_storage",
            "workflow_storage_io",
            "workflow_storage_context",
        )
        for name in modules:
            source = (root / "contracts" / (name + ".py")).read_text()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(
                        node.module.startswith(
                            (
                                "agent_lifecycle.workflow",
                                "agent_lifecycle.accounting",
                            )
                        )
                    )
                    self.assertNotIn("workflow_state_authority", node.module)
        for name in ("storage", "storage_io"):
            source = (root / "workflow" / (name + ".py")).read_text()
            tree = ast.parse(source)
            kinds = (ast.FunctionDef, ast.ClassDef)
            defined = any(isinstance(node, kinds) for node in ast.walk(tree))
            self.assertFalse(defined)


if __name__ == "__main__":
    unittest.main()
