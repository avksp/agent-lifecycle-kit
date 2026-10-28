"""Component storage proof; these fixtures do not accept native tasks."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.workflow_storage import (
    PreparedStorage,
    iter_historical_snapshots,
    load_object,
    persist_storage,
    prepare_storage,
    task_evidence,
    validate_storage,
)
from agent_lifecycle.contracts.workflow_storage_schemas import (
    MAX_RETAINED_BYTES,
    REFERENCE_VERSION,
    item_counts,
)


def state_fixture():
    state = {
        "schemaVersion": "agent-workflow-state.v4",
        "runId": "run",
        "packageId": "package",
        "planRevision": 2,
        "planDigest": "2" * 64,
        "sourceRevision": "source",
        "operationLedger": {},
        "budgets": {"maxTaskAttempts": 2},
    }
    receipt = {
        "schemaVersion": "agent-task-ownership-receipt.v1",
        "runId": "run",
        "packageId": "package",
        "taskId": "T",
        "attempt": 1,
        "planDigest": "2" * 64,
        "sourceRevision": "source",
        "entries": [{"path": "src/x", "category": "task-owned"}],
        "blockers": [],
        "changedFileCount": 1,
        "status": "PASS",
    }
    state["tasks"] = [
        {
            "id": "T",
            "attempt": 1,
            "status": "ACCEPTED",
            "ownershipReceipt": receipt,
            "attemptHistory": [],
            "resultChangeSetEvidence": {
                "schemaVersion": "agent-task-change-set-evidence.v1",
                "entries": [],
                "snapshotHash": "a" * 64,
            },
            "result": {"sha256": "c" * 64, "bytes": 10, "path": "result.json"},
        }
    ]
    snapshot = {
        key: deepcopy(state[key])
        for key in (
            "runId",
            "packageId",
            "planRevision",
            "planDigest",
            "sourceRevision",
            "tasks",
        )
    }
    snapshot["financialRole"] = (
        "HISTORICAL_ALREADY_INCLUDED_"  # Preserve the accounting role.
        "IN_CUMULATIVE_ACCOUNTING"
    )
    state["priorSnapshots"] = [snapshot]
    return state


def scale_fixture(*, distinct=False):
    state = state_fixture()
    state["tasks"] = [
        {"id": f"T{index}", "attempt": 1, "attemptHistory": []}
        for index in range(
            32,
        )
    ]
    state["operationLedger"] = {
        f"operation-{index}": {"eventType": "fixture"}
        for index in range(
            2048,
        )
    }
    state["priorSnapshots"] = []
    for revision in range(128):
        snapshot = {
            key: deepcopy(state[key])
            for key in (
                "runId",
                "packageId",
                "sourceRevision",
                "tasks",
            )
        }
        snapshot.update(
            planRevision=revision,
            planDigest=canonical_digest({"revision": revision}),
            financialRole=(
                "HISTORICAL_ALREADY_INCLUDED_"  # Historical accounting role.
                "IN_CUMULATIVE_ACCOUNTING"
            ),
        )
        for index, task in enumerate(snapshot["tasks"]):
            if distinct and revision >= 124:
                continue
            task["resultChangeSetEvidence"] = {
                "schemaVersion": "agent-task-change-set-evidence.v1",
                "entries": [],
                "fixtureObject": revision * 32 + index if distinct else 0,
            }
        state["priorSnapshots"].append(snapshot)
    return state


def initial_snapshot_fixture():
    state = state_fixture()
    state["priorSnapshots"].insert(
        0,
        {
            "runId": state["runId"],
            "packageId": state["packageId"],
            "planRevision": 0,
            "planDigest": "",
            "sourceRevision": "",
            "tasks": [],
            "taskSummary": {},
            "phase": "AWAITING_AUTHORIZATION",
            "immutableInput": None,
            "archivedAt": "2026-10-26T22:24:10Z",
            "financialRole": ("HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING"),
        },
    )
    return state


def snapshot_object(body, lineage):
    data = canonical_bytes(body) + b"\n"
    digest = canonical_digest(body)
    reference = {
        "schemaVersion": REFERENCE_VERSION,
        "kind": "plan-snapshot",
        "sha256": digest,
        "bytes": len(data),
        "path": f"objects/{digest}.json",
        "lineage": deepcopy(lineage),
        "itemCounts": item_counts(body),
    }
    return reference, data


class StateStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def prepared(self, state=None):
        return prepare_storage(
            state if state is not None else state_fixture(),
            storage_root="work/storage",
        )

    def test_initial_snapshot_preserves_exact_body_through_all_readers(self):
        state = initial_snapshot_fixture()
        original = deepcopy(state)
        prepared = self.prepared(state)
        reference = prepared.state["priorSnapshots"][0]
        body = original["priorSnapshots"][0]
        self.assertEqual(state, original)
        self.assertEqual(reference["itemCounts"], {"tasks": 0})
        self.assertEqual(
            prepared.objects[reference["path"]],
            canonical_bytes(body) + b"\n",
        )
        persist_storage(self.root, prepared)
        validate_storage(self.root, prepared.state)
        self.assertEqual(load_object(self.root, prepared.state, reference), body)
        snapshots = list(iter_historical_snapshots(self.root, prepared.state))
        self.assertEqual(snapshots[0], body)
        self.assertEqual(len(snapshots), len(original["priorSnapshots"]))

    def test_initial_snapshot_invalid_inline_bodies_never_publish(self):
        initial = initial_snapshot_fixture()["priorSnapshots"][0]
        leaf = self.prepared().state["tasks"][0]["ownershipReceipt"]
        variants = [
            ("tasks", [{}]),
            ("planRevision", False),
            ("planRevision", 1),
            ("planDigest", "1" * 64),
            ("sourceRevision", "source"),
            ("runId", "OTHER"),
            ("packageId", "OTHER"),
            ("financialRole", "CURRENT"),
            ("ownershipReceipt", {"status": "PASS"}),
            ("hidden", {"nested": [leaf]}),
            ("hidden", {"resultChangeSetEvidence": {"entries": []}}),
            ("hidden", {"schemaVersion": "agent-task-ownership-receipt.v1"}),
        ]
        for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision", "tasks"):
            variants.append((key, None))
        for key, value in variants:
            state = initial_snapshot_fixture()
            changed = deepcopy(initial)
            if value is None:
                changed.pop(key)
            else:
                changed[key] = value
            state["priorSnapshots"][0] = changed
            with self.subTest(key=key, value=value):
                with self.assertRaises(LifecycleError):
                    self.prepared(state)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_initial_snapshot_forged_bodies_fail_complete_preflight(self):
        prepared = self.prepared(initial_snapshot_fixture())
        original = initial_snapshot_fixture()["priorSnapshots"][0]
        initial_reference = prepared.state["priorSnapshots"][0]
        bodies = []
        for field in initial_reference["lineage"]:
            changed = deepcopy(original)
            changed.pop(field)
            bodies.append((f"missing-{field}", changed))
        for field, value in (
            ("planRevision", False),
            ("planRevision", 0.0),
            ("runId", "OTHER"),
            ("tasks", [{}]),
            ("hidden", {"ownershipReceipt": {"status": "PASS"}}),
            ("hidden", {"leaf": prepared.state["tasks"][0]["ownershipReceipt"]}),
        ):
            changed = deepcopy(original)
            changed[field] = value
            bodies.append((field, changed))
        for name, body in bodies:
            reference, data = snapshot_object(body, initial_reference["lineage"])
            state = deepcopy(prepared.state)
            state["priorSnapshots"][0] = reference
            objects = dict(prepared.objects)
            objects.pop(initial_reference["path"])
            objects[reference["path"]] = data
            with self.subTest(name=name), self.assertRaises(LifecycleError):
                persist_storage(self.root, PreparedStorage(state, objects))
            self.assertEqual(list(self.root.iterdir()), [])

    def test_initial_snapshot_wrong_run_counts_and_duplicate_slots_refuse(self):
        prepared = self.prepared(initial_snapshot_fixture())
        for variant in ("run", "package", "count", "duplicate"):
            state = deepcopy(prepared.state)
            reference = state["priorSnapshots"][0]
            if variant == "count":
                reference["itemCounts"]["tasks"] = 1
            elif variant == "duplicate":
                state["priorSnapshots"].append(deepcopy(reference))
            else:
                reference["lineage"][f"{variant}Id"] = "OTHER"
            with self.subTest(variant=variant), self.assertRaises(LifecycleError):
                persist_storage(
                    self.root,
                    PreparedStorage(state, prepared.objects),
                )
            self.assertEqual(list(self.root.iterdir()), [])

    def test_accessor_validates_bad_history_before_none_or_inline(self):
        prepared = self.prepared()
        persist_storage(self.root, prepared)
        historical = prepared.state["priorSnapshots"][0]
        path = self.root / "work/storage" / historical["path"]
        path.write_bytes(b"{}\n")
        for variant in ("absent", "inline"):
            task = deepcopy(prepared.state["tasks"][0])
            if variant == "absent":
                task.pop("ownershipReceipt")
            else:
                task["ownershipReceipt"] = {"status": "PASS"}
            with (
                self.subTest(variant=variant),
                self.assertRaises(
                    LifecycleError,
                ),
            ):
                task_evidence(
                    self.root,
                    prepared.state,
                    task,
                    "ownershipReceipt",
                )

    def test_accessor_refuses_detached_kind_task_attempt_or_inline(self):
        prepared = self.prepared()
        persist_storage(self.root, prepared)
        for variant in (
            "kind",
            "task",
            "attempt",
            "lineage",
            "inline",
            "false-absence",
        ):
            task = deepcopy(prepared.state["tasks"][0])
            if variant == "kind":
                task["ownershipReceipt"] = task["resultChangeSetEvidence"]
            elif variant == "task":
                task["id"] = "OTHER"
            elif variant == "attempt":
                task["attempt"] = 2
            elif variant == "lineage":
                task["ownershipReceipt"]["lineage"]["planRevision"] = 999
            elif variant == "false-absence":
                task.pop("ownershipReceipt")
            else:
                task["ownershipReceipt"] = {"status": "PASS"}
            with (
                self.subTest(variant=variant),
                self.assertRaises(
                    LifecycleError,
                ),
            ):
                task_evidence(
                    self.root,
                    prepared.state,
                    task,
                    "ownershipReceipt",
                )

    def test_accessor_keeps_v4_inline_and_v5_absence_after_validation(self):
        legacy = state_fixture()
        task = legacy["tasks"][0]
        self.assertEqual(
            task_evidence(self.root, legacy, task, "ownershipReceipt"),
            task["ownershipReceipt"],
        )
        legacy["tasks"][0].pop("ownershipReceipt")
        prepared = self.prepared(legacy)
        persist_storage(self.root, prepared)
        detached = deepcopy(prepared.state["tasks"][0])
        self.assertIsNone(
            task_evidence(
                self.root,
                prepared.state,
                detached,
                "ownershipReceipt",
            )
        )

    def test_accessor_reads_each_graph_object_once_with_selected_body(self):
        from agent_lifecycle.contracts import workflow_storage_io as storage

        prepared = self.prepared()
        persist_storage(self.root, prepared)
        task = deepcopy(prepared.state["tasks"][0])
        observe_reads = patch.object(
            storage,
            "read_authority_bytes",
            wraps=storage.read_authority_bytes,
        )
        with observe_reads as reads:
            body = task_evidence(
                self.root,
                prepared.state,
                task,
                "ownershipReceipt",
            )
        self.assertEqual(body["taskId"], "T")
        self.assertEqual(reads.call_count, 3)

    @contextmanager
    def vanishing_entry(self, trigger):
        from agent_lifecycle.contracts import workflow_storage_io as storage_io

        original = storage_io.os.scandir
        scans = 0

        class Vanishing:
            name = "vanishing"

            def stat(inner, *, follow_symlinks):
                del inner, follow_symlinks
                (self.root / "work/storage/objects/vanishing").unlink()
                raise FileNotFoundError("fixture descendant disappeared")

        @contextmanager
        def scan(target):
            nonlocal scans
            with original(target) as entries:
                selected = []
                for entry in entries:
                    if entry.name == "vanishing":
                        scans += 1
                        if scans == trigger:
                            selected.append(Vanishing())
                            continue
                    selected.append(entry)
                yield iter(selected)

        with patch.object(storage_io.os, "scandir", scan):
            yield

    def test_retained_scan_disappearance_refuses_with_remaining_bytes(self):
        from agent_lifecycle.contracts.workflow_storage_io import retained_bytes

        prepared = self.prepared()
        directory = self.root / "work/storage/objects"
        directory.mkdir(parents=True)
        (directory / "remaining").write_bytes(b"retained")
        (directory / "vanishing").write_bytes(b"x")
        with (
            self.vanishing_entry(1),
            self.assertRaises(LifecycleError) as caught,
        ):
            retained_bytes(
                self.root,
                prepared.state["storage"],
                time.monotonic() + 30,
            )
        self.assertEqual(caught.exception.code, "workflow-storage-changed")
        self.assertEqual((directory / "remaining").read_bytes(), b"retained")

    def test_preflight_disappearance_cannot_publish_beyond_retained_limit(self):
        prepared = self.prepared()
        directory = self.root / "work/storage/objects"
        directory.mkdir(parents=True)
        with (directory / "remaining").open("wb") as handle:
            handle.truncate(MAX_RETAINED_BYTES - 2)
        (directory / "vanishing").write_bytes(b"x")
        with (
            self.vanishing_entry(2),
            self.assertRaises(LifecycleError) as caught,
        ):
            persist_storage(self.root, prepared)
        self.assertEqual(caught.exception.code, "workflow-storage-changed")
        self.assertEqual({p.name for p in directory.iterdir()}, {"remaining"})

    def test_pure_preparation_deduplicates_exact_bytes_identities(self):
        original = state_fixture()
        before = canonical_bytes(original)
        prepared = self.prepared(original)
        self.assertEqual(canonical_bytes(original), before)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(len(prepared.objects), 3)
        task = prepared.state["tasks"][0]
        self.assertEqual(task["result"], original["tasks"][0]["result"])
        reference = task["ownershipReceipt"]
        receipt = original["tasks"][0]["ownershipReceipt"]
        self.assertEqual(reference["sha256"], canonical_digest(receipt))
        self.assertEqual(
            prepared.objects[reference["path"]],
            canonical_bytes(receipt) + b"\n",
        )
        persist_storage(self.root, prepared)
        report = validate_storage(self.root, prepared.state)
        self.assertEqual(report.object_reads, 3)
        self.assertEqual(report.object_count, 3)
        self.assertEqual(
            task_evidence(self.root, prepared.state, task, "ownershipReceipt"),
            receipt,
        )
        historical = list(iter_historical_snapshots(self.root, prepared.state))
        self.assertEqual(
            historical[0]["financialRole"],
            ("HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING"),
        )

    def test_retry_reuses_same_byte_orphans_without_replacement(self):
        prepared = self.prepared()
        persist_storage(self.root, prepared)
        identities = {
            path: (path.stat().st_ino, path.read_bytes())
            for path in prepared.writes(
                self.root,
            )
        }
        persist_storage(self.root, prepared)
        self.assertEqual(
            identities,
            {
                path: (path.stat().st_ino, path.read_bytes())
                for path in prepared.writes(
                    self.root,
                )
            },
        )

    def test_any_existing_conflict_prevents_all_new_writes(self):
        prepared = self.prepared()
        name = next(reversed(prepared.objects))
        selected = self.root / prepared.state["storage"]["root"] / name
        selected.parent.mkdir(parents=True)
        selected.write_bytes(b"wrong\n")
        with self.assertRaises(LifecycleError) as caught:
            persist_storage(self.root, prepared)
        self.assertEqual(
            caught.exception.code,
            "workflow-storage-object-conflict",
        )
        self.assertEqual(list(selected.parent.iterdir()), [selected])

    def test_damaged_unselected_historical_leaf_blocks_future_publication(self):
        state = state_fixture()
        previous = state["priorSnapshots"][0]["tasks"][0]
        previous["resultChangeSetEvidence"]["snapshotHash"] = "b" * 64
        prepared = self.prepared(state)
        persist_storage(self.root, prepared)
        snapshot_ref = prepared.state["priorSnapshots"][0]
        import json

        snapshot = json.loads(prepared.objects[snapshot_ref["path"]])
        leaf = snapshot["tasks"][0]["resultChangeSetEvidence"]
        path = self.root / "work/storage" / leaf["path"]
        path.write_bytes(b"{}\n")
        next_state = deepcopy(prepared.state)
        next_state["tasks"][0]["resultChangeSetEvidence"] = {
            "schemaVersion": "agent-task-change-set-evidence.v1",
            "entries": [{"changed": True}],
        }
        prospective = prepare_storage(next_state)
        before = set((self.root / "work/storage/objects").iterdir())
        with self.assertRaises(LifecycleError):
            persist_storage(self.root, prospective)
        self.assertEqual(
            before,
            set((self.root / "work/storage/objects").iterdir()),
        )

    def test_reference_negative_matrix_refuses_before_writes(self):
        for field, value in (
            ("bytes", 10),
            ("sha256", "f" * 64),
            ("path", "objects/../escape.json"),
            ("kind", "result-change-set-evidence"),
            ("lineage", {"runId": "other"}),
            ("itemCounts", {"entries": 900}),
        ):
            prepared = self.prepared()
            prepared.state["tasks"][0]["ownershipReceipt"][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                persist_storage(self.root, prepared)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_tampered_truncated_oversized_noncanonical_objects_re(self):
        for variant in ("missing", "tamper", "truncated", "large", "spaces"):
            with (
                self.subTest(
                    variant=variant,
                ),
                tempfile.TemporaryDirectory() as t,
            ):
                root = Path(t)
                prepared = self.prepared()
                persist_storage(root, prepared)
                path = next(iter(prepared.writes(root)))
                original = path.read_bytes()
                if variant == "missing":
                    path.unlink()
                else:
                    path.write_bytes(
                        {
                            "tamper": original.replace(b"PASS", b"FAIL"),
                            "truncated": original[:-2],
                            "large": b"x" * 1_048_577,
                            "spaces": original + b" ",
                        }[variant]
                    )
                with self.assertRaises(LifecycleError):
                    validate_storage(root, prepared.state)

    def test_symlink_directory_and_object_refuse_without_following(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "work").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(LifecycleError):
            persist_storage(self.root, self.prepared())
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / "work").unlink()
        prepared = self.prepared()
        persist_storage(self.root, prepared)
        path = next(iter(prepared.writes(self.root)))
        data = path.read_bytes()
        path.unlink()
        target = outside / "leaf.json"
        target.write_bytes(data)
        path.symlink_to(target)
        with self.assertRaises(LifecycleError):
            validate_storage(self.root, prepared.state)
        self.assertEqual(target.read_bytes(), data)

    def test_arbitrary_nested_references_and_recursive_snapshots_refuse(self):
        prepared = self.prepared()
        prepared.state["hidden"] = deepcopy(
            prepared.state["tasks"][0]["ownershipReceipt"],
        )
        with self.assertRaises(LifecycleError):
            persist_storage(self.root, prepared)
        state = state_fixture()
        state["priorSnapshots"][0]["priorSnapshots"] = [{}]
        with self.assertRaises(LifecycleError):
            self.prepared(state)
        prepared = self.prepared()
        prepared.state["priorSnapshots"].append(
            deepcopy(prepared.state["priorSnapshots"][0]),
        )
        with self.assertRaises(LifecycleError):
            persist_storage(self.root, prepared)

    def test_one_oversized_leaf_and_residual_root_refuse_honestly(self):
        for category in ("leaf", "root"):
            state = state_fixture()
            target = state
            if category == "leaf":
                target = state["tasks"][0]["ownershipReceipt"]
            target["padding"] = "x" * 1_048_576
            with (
                self.subTest(category=category),
                self.assertRaises(
                    LifecycleError,
                ) as caught,
            ):
                self.prepared(state)
            self.assertEqual(
                caught.exception.code,
                ("workflow-storage-capacity-exceeded"),
            )
            self.assertIn("required", caught.exception.details)

    def test_count_limits_and_reachable_byte_preflight(self):
        from agent_lifecycle.contracts import workflow_storage as storage

        for field, count in (
            ("tasks", 33),
            ("priorSnapshots", 129),
            ("operationLedger", 2049),
        ):
            state = state_fixture()
            state[field] = (
                {
                    str(i): {}
                    for i in range(
                        count,
                    )
                }
                if (field == "operationLedger")
                else [{} for _ in range(count)]
            )
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                self.prepared(state)
        prepared = self.prepared()
        with (
            patch.object(storage, "MAX_REACHABLE_BYTES", 10),
            self.assertRaises(LifecycleError) as caught,
        ):
            validate_storage(self.root, prepared.state, prepared=prepared)
        self.assertEqual(caught.exception.details["category"], "reachableBytes")

    def test_orphan_retained_capacity_is_checked_before_creates(self):
        directory = self.root / "work/storage/objects"
        directory.mkdir(parents=True)
        with (directory / "unreachable").open("wb") as handle:
            handle.truncate(MAX_RETAINED_BYTES)
        with self.assertRaises(LifecycleError) as caught:
            persist_storage(self.root, self.prepared())
        self.assertEqual(caught.exception.details["category"], "retainedBytes")
        self.assertEqual(len(list(directory.iterdir())), 1)

    def test_deadline_and_two_reader_two_writer_same_byte_races(self):
        prepared = self.prepared()
        with self.assertRaises(LifecycleError) as caught:
            validate_storage(
                self.root,
                prepared.state,
                prepared=prepared,
                deadline=time.monotonic() - 1,
            )
        self.assertEqual(
            caught.exception.code,
            ("workflow-storage-deadline-exceeded"),
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [
                workers.submit(
                    persist_storage,
                    self.root,
                    prepared,
                )
                for _ in range(2)
            ]
            successes = 0
            for future in futures:
                try:
                    future.result()
                    successes += 1
                except LifecycleError as error:
                    # Concurrent uncommitted file bytes are never trusted.
                    if os.name == "nt" and error.code == "authority-input-unavailable":
                        self.assertIs(type(error.details.get("winerror")), int, error.details)
                        self.assertEqual(error.details.get("winerror"), 32, error.details)
                        self.assertIn(error.details.get("operation"), {"read", "sync"}, error.details)
                    else:
                        self.assertIn(
                            error.code,
                            {
                                "authority-input-changed",
                                "workflow-storage-changed",
                                "workflow-storage-object-conflict",
                            },
                            error.details,
                        )
            self.assertGreaterEqual(successes, 1)
            persist_storage(self.root, prepared)
            readers = [
                workers.submit(
                    validate_storage,
                    self.root,
                    prepared.state,
                )
                for _ in range(2)
            ]
            self.assertEqual([r.result().object_count for r in readers], [3, 3])

    @unittest.skipUnless(os.name == "nt", "Native Windows sharing proof requires Windows")
    def test_windows_held_directory_sharing_refusal_preserves_components_and_retry(self):
        from agent_lifecycle.contracts import authority_io

        prepared = self.prepared()
        persist_storage(self.root, prepared)
        directory = self.root / prepared.state["storage"]["root"] / "objects"
        before = {path.name: path.read_bytes() for path in directory.iterdir()}
        handle = authority_io._windows_directory(directory, writable=True)
        try:
            with self.assertRaises(LifecycleError) as caught:
                persist_storage(self.root, prepared)
        finally:
            authority_io._windows_close(handle)
        error = caught.exception
        self.assertEqual(error.code, "authority-input-unavailable", error.details)
        self.assertIs(type(error.details.get("winerror")), int, error.details)
        self.assertEqual(error.details.get("winerror"), 32, error.details)
        self.assertIn(error.details.get("operation"), {"read", "sync"}, error.details)
        self.assertEqual({path.name: path.read_bytes() for path in directory.iterdir()}, before)
        persist_storage(self.root, prepared)
        validation = validate_storage(self.root, prepared.state)
        self.assertEqual(validation.object_count, 3)
        self.assertEqual({path.name: path.read_bytes() for path in directory.iterdir()}, before)
        print(
            "WINDOWS_STORAGE_SHARING_PROOF="
            + json.dumps(
                {
                    "nativeWindows": True,
                    "winerror": error.details["winerror"],
                    "operation": error.details["operation"],
                    "unchangedComponents": len(before),
                    "retryObjectCount": validation.object_count,
                },
                sort_keys=True,
            )
        )

    def test_interrupted_write_keeps_orphans_and_retry_completes(self):
        from agent_lifecycle.contracts import workflow_storage_io as storage_io

        prepared = self.prepared()
        real = storage_io.create_authority_bytes
        calls = 0

        def interrupt(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("fixture interruption")
            return real(*args, **kwargs)

        with (
            patch.object(storage_io, "create_authority_bytes", interrupt),
            self.assertRaises(OSError),
        ):
            persist_storage(self.root, prepared)
        self.assertEqual(
            len(list((self.root / "work/storage/objects").iterdir())),
            1,
        )
        persist_storage(self.root, prepared)
        self.assertEqual(
            validate_storage(self.root, prepared.state).object_count,
            3,
        )

    def test_attempt_history_receipts_are_compacted_and_never_truncated(self):
        state = state_fixture()
        previous = deepcopy(state["tasks"][0])
        previous["attempt"] = previous["ownershipReceipt"]["attempt"] = 0
        previous.pop("attemptHistory")
        state["tasks"][0]["attemptHistory"] = [previous]
        prepared = self.prepared(state)
        history = prepared.state["tasks"][0]["attemptHistory"]
        self.assertEqual(len(history), 1)
        self.assertEqual(
            history[0]["ownershipReceipt"]["lineage"]["attempt"],
            0,
        )
        persist_storage(self.root, prepared)

    def test_accepted_original_plan_lineage_survives_current_plan_change(self):
        state = state_fixture()
        first = self.prepared(state)
        persist_storage(self.root, first)
        later = deepcopy(first.state)
        later.update(planRevision=3, planDigest="3" * 64, sourceRevision="new")
        later["tasks"][0]["adoptedFromPlanRevision"] = 2
        second = prepare_storage(later)
        persist_storage(self.root, second)
        reference = second.state["tasks"][0]["ownershipReceipt"]
        self.assertEqual(reference["lineage"]["planDigest"], "2" * 64)
        self.assertEqual(reference["lineage"]["sourceRevision"], "source")

    def test_unreachable_prepared_objects_never_publish(self):
        prepared = self.prepared()
        data = b'{"unused":true}\n'
        extra = {
            **prepared.objects,
            f"objects/{canonical_digest({'unused': True})}.json": data,
        }
        with self.assertRaises(LifecycleError):
            persist_storage(self.root, PreparedStorage(prepared.state, extra))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_combined_32_tasks_128_snapshots_2048_operations_is_bounded(self):
        prepared = self.prepared(scale_fixture())
        self.assertLessEqual(
            len(canonical_bytes(prepared.state)) + 1,
            768 * 1024,
        )
        persist_storage(self.root, prepared)
        validation = validate_storage(self.root, prepared.state)
        self.assertEqual(validation.object_count, 129)
        self.assertEqual(validation.object_reads, 129)
        self.assertEqual(
            len(list(iter_historical_snapshots(self.root, prepared.state))),
            128,
        )
        self.assertTrue(
            {
                "tasks",
                "priorSnapshots",
                "operationLedger",
            }.issubset(validation.warnings)
        )

    def test_exact_4096_distinct_reachable_objects_and_one_more_refuses(self):
        state = scale_fixture(distinct=True)
        prepared = self.prepared(state)
        validation = validate_storage(
            self.root,
            prepared.state,
            prepared=prepared,
        )
        self.assertEqual(validation.object_count, 4096)
        self.assertEqual(validation.object_reads, 0)
        state["tasks"][0]["resultChangeSetEvidence"] = {
            "schemaVersion": "agent-task-change-set-evidence.v1",
            "entries": [],
            "fixtureObject": "one-more",
        }
        with self.assertRaises(LifecycleError) as caught:
            self.prepared(state)
        self.assertEqual(
            caught.exception.details["category"],
            "reachableObjects",
        )

    def test_attempt_ceiling_is_enforced_without_truncation(self):
        state = state_fixture()
        state["tasks"][0]["attemptHistory"] = [{}, {}, {}]
        with self.assertRaises(LifecycleError):
            self.prepared(state)
        self.assertEqual(len(state["tasks"][0]["attemptHistory"]), 3)

    def test_repeated_v4_adoption_recovers_original_receipt_plan_revision(self):
        state = state_fixture()
        state.update(planRevision=4, planDigest="4" * 64)
        task = state["tasks"][0]
        task["adoptedFromPlanRevision"] = 3
        prepared = self.prepared(state)
        reference = prepared.state["tasks"][0]["ownershipReceipt"]
        self.assertEqual(reference["lineage"]["planRevision"], 2)
        self.assertEqual(reference["lineage"]["planDigest"], "2" * 64)
        persist_storage(self.root, prepared)


if __name__ == "__main__":
    unittest.main()
