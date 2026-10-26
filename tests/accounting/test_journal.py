"""Finite P01 storage witnesses. Fixtures are not provider attestations."""

import copy
import hashlib
import json
import multiprocessing
import os
import queue
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing, nullcontext
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_lifecycle.accounting.contracts import (
    MAX_INTEGER,
    AuthoritativeReceipt,
    BudgetPolicy,
    BudgetScope,
    EvidenceRef,
    OpeningBalance,
    Operation,
    canonical,
    digest,
    uint,
)
from agent_lifecycle.accounting.journal import (
    Journal,
    JournalUnavailable,
    RevisionConflict,
    _apply,
    _apply_delta,
    _apply_delta_encoded,
    _Lease,
    _state_delta,
)

PROOF = EvidenceRef("fixture:trusted-controller", "a" * 64)


def operation(scope="run", name="op", task="task", upper=100, closeout=False):
    return Operation(
        budget_scope_id=scope,
        operation_id=name,
        dispatch_key="dispatch:" + name,
        run_id=scope,
        task_id=task,
        role="worker" if task else "coordinator",
        attempt_id="attempt:1",
        retry_ordinal=0,
        attribution_reason="fixture attribution",
        policy_id="policy",
        policy_revision=1,
        route_id="fixture:route",
        source_id="fixture:source",
        unit_definition_id="reportedTokens:fixture:v1",
        upper_bound_tokens=upper,
        permit_id=scope + ":permit:" + name,
        input_digest="b" * 64,
        route_qualification=PROOF,
        issuer=PROOF,
        validity=PROOF,
        operation_class="CLOSEOUT" if closeout else "ORDINARY",
        closeout_allocation_id=(task if task is not None else "") if closeout else None,
    )


def receipt(op, actual=80, event=None):
    return AuthoritativeReceipt(
        receipt_id="receipt:" + op.operation_id,
        budget_scope_id=op.budget_scope_id,
        operation_id=op.operation_id,
        dispatch_key=op.dispatch_key,
        permit_id=op.permit_id,
        binding_digest=op.binding_digest,
        attempt_id=op.attempt_id,
        route_id=op.route_id,
        source_id=op.source_id,
        source_event_id=event or op.budget_scope_id + ":" + op.operation_id,
        source_schema_version="fixture:v1",
        unit_definition_id=op.unit_definition_id,
        reported_tokens=actual,
        coverage=PROOF,
        raw_evidence=PROOF,
        attestation=PROOF,
    )


def open_scope(journal, scope="run", *, cap=1000, protected=None, spent=0, overhead=0, pending=(), covered=()):
    return journal.open_scope(
        BudgetScope(scope, scope, "reportedTokens:fixture:v1"),
        BudgetPolicy("policy", 1, cap, {"task": cap}, protected or {}, PROOF),
        OpeningBalance(
            "opening",
            "fixture:source",
            "reportedTokens:fixture:v1",
            {"task": spent},
            overhead,
            pending,
            PROOF,
            PROOF,
            covered,
        ),
    )


def concurrent_worker(path, barrier, output, action, name):
    try:
        with Journal(path, PROOF) as journal:
            barrier.wait(timeout=10)
            if action == "claim":
                op = operation()
                result = journal.claim("run", "op", op.binding_digest, name)
            else:
                result = journal.reserve(operation(name=name, upper=60), expected_revision=1)
            output.put(result)
    except RevisionConflict:
        output.put("REVISION_CONFLICT")
    except JournalUnavailable as exc:
        output.put(f"UNAVAILABLE: {exc!r}; cause={exc.__cause__!r}; write_outcome={exc.write_outcome!r}")


def crash_worker(path, stage):
    with Journal(path, PROOF) as journal:
        op = operation()
        if stage == "before_commit":
            journal.fault_hook = lambda point: os._exit(17) if point == "after_event" else None
            journal.reserve(op)
        elif stage == "after_claim":
            journal.reserve(op)
            journal.claim("run", "op", op.binding_digest, "claim")
        else:
            journal.reserve(op)
            journal.claim("run", "op", op.binding_digest, "claim")
            journal.record_settlement(receipt(op))
        os._exit(17)


def admission_worker(path, ready, start, output, name, crash=False, fixture_queue_seconds=None):
    with Journal(path, PROOF) as journal:
        ready.set()
        if not start.wait(10):
            raise RuntimeError("Fixture start deadline")
        if crash:
            with journal._write_admission():
                output.put((name, "HOLDING"))
                output.close()
                output.join_thread()
                time.sleep(10)
        else:
            original_slot = journal._queue.slot

            def fixture_slot(observation, *, timeout):
                if timeout != 1.0 or fixture_queue_seconds != 10.0:
                    raise AssertionError("Expected real1second request and explicit10second fixture allowance")
                observation.update(product_requested_seconds=timeout, fixture_queue_seconds=fixture_queue_seconds)
                return original_slot(observation, timeout=fixture_queue_seconds)

            scope = (
                mock.patch.object(journal._queue, "slot", side_effect=fixture_slot)
                if fixture_queue_seconds is not None else nullcontext()
            )
            with scope:
                result = journal.reserve(operation(name=name, upper=1))
            output.put((name, result, journal.last_write_admission))


def fresh_admission_worker(path, start, output, deadline=None):
    deadline = time.monotonic() + 10 if deadline is None else deadline
    attempts = 0
    try:
        if not start.wait(max(0, deadline - time.monotonic())):
            raise TimeoutError("Fresh constructor start deadline expired")
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Fresh constructor shared deadline expired")
            attempts += 1
            try:
                with Journal(path, PROOF) as journal:
                    configuration = journal.configuration
            except JournalUnavailable as exc:
                if str(exc) != "Write admission deadline expired" or exc.write_outcome != "NOT_STARTED":
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(0.01, remaining))
            else:
                output.put({"status": "OK", "pid": os.getpid(), "attempts": attempts, "configuration": configuration})
                return
    except Exception as exc:
        output.put(
            {
                "status": "ERROR",
                "pid": os.getpid(),
                "attempts": attempts,
                "errorType": type(exc).__name__,
                "message": str(exc),
                "write_outcome": getattr(exc, "write_outcome", None),
            }
        )
        raise
    finally:
        output.close()
        output.join_thread()


def fork_lease_owner(path, ready_path, child_path):
    with Journal(path, PROOF) as journal:
        with journal._write_admission():
            owner = os.getpid()
            child = os.fork()
            if child == 0:
                try:
                    refused = False
                    try:
                        journal.snapshot("run")
                    except JournalUnavailable as exc:
                        refused = exc.write_outcome == "NOT_STARTED"
                    deadline = time.monotonic() + 15
                    target = Path(child_path)
                    while time.monotonic() < deadline:
                        data = {
                            "pid": os.getpid(),
                            "owner": owner,
                            "orphan": os.getppid() != owner,
                            "inherited_refused": refused,
                            "heartbeat": time.monotonic(),
                        }
                        staged = target.with_suffix(".tmp")
                        staged.write_text(json.dumps(data), encoding="utf-8", newline="\n")
                        staged.replace(target)
                        time.sleep(0.01)
                finally:
                    os._exit(0)
            staged_ready = Path(ready_path).with_suffix(".tmp")
            staged_ready.write_text(json.dumps({"owner": owner, "child": child}), encoding="utf-8", newline="\n")
            staged_ready.replace(ready_path)
            time.sleep(15)  # Test kills owner, forbidding normal dequeue.


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "journal.db"
        self.j = Journal(self.path, PROOF)
        open_scope(self.j)

    def tearDown(self):
        self.j.close()
        self.temp.cleanup()

    def claimed(self, op=None):
        op = op or operation()
        self.assertEqual(self.j.reserve(op), "RESERVED")
        self.assertEqual(self.j.claim(op.budget_scope_id, op.operation_id, op.binding_digest, "claim"), "CLAIM_GRANTED")
        return op

    def test_write_admission_fifo_and_dead_holder(self):
        ctx = multiprocessing.get_context("spawn")
        output = ctx.Queue()
        ready = [ctx.Event() for _ in range(3)]
        starts = [ctx.Event() for _ in range(3)]
        children = [
            ctx.Process(target=admission_worker, args=(str(self.path), ready[i], starts[i], output, str(i), i == 2))
            for i in range(3)
        ]
        try:
            for child in children:
                child.start()
            self.assertTrue(all(event.wait(10) for event in ready))
            with self.j._write_admission():
                for i in (0, 1):
                    starts[i].set()
                    deadline = time.monotonic() + 0.7
                    while len(list(self.j._queue.directory.glob("*-*"))) < i + 2:
                        self.assertLess(time.monotonic(), deadline, "Waiter registration stalled")
                        time.sleep(0.002)
            results = [output.get(timeout=10), output.get(timeout=10)]
            by_id = {row[0]: row for row in results}
            self.assertEqual(set(by_id), {"0", "1"})
            self.assertTrue(all(row[1] == "RESERVED" and row[2]["status"] == "ADMITTED" for row in results))
            self.assertLess(by_id["0"][2]["ticket"], by_id["1"][2]["ticket"])
            committed = [
                json.loads(row["payload"])["operation"]["operation_id"]
                for row in self.j.events("run")
                if row["kind"] == "RESERVE"
            ]
            self.assertEqual(committed, ["0", "1"])
            self.assertEqual(self.j.snapshot("run").active_reservations, 2)
            starts[2].set()
            self.assertEqual(output.get(timeout=10), ("2", "HOLDING"))
            children[2].kill()
            children[2].join(5)
            self.assertEqual(self.j.reserve(operation(name="after-death", upper=1)), "RESERVED")
            self.assertEqual(self.j.snapshot("run").active_reservations, 3)
        finally:
            for child in children:
                child.join(2)
                if child.is_alive():
                    child.kill()
                    child.join(2)
            output.close()
            output.join_thread()

    def test_write_admission_timeout_external_busy_and_commit_uncertainty(self):
        with Journal(self.path, PROOF) as other:
            before = self.j.snapshot("run")
            with self.j._write_admission():
                begin = time.monotonic()
                with self.assertRaises(JournalUnavailable) as caught:
                    other.reserve(operation())
                self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
                self.assertLess(time.monotonic() - begin, 2)
                self.assertEqual(other.last_write_admission["status"], "REFUSED")
            self.assertEqual(self.j.snapshot("run"), before)
            self.j._db.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(JournalUnavailable) as caught:
                    other.reserve(operation())
                self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
                self.assertIsInstance(caught.exception.__cause__, sqlite3.OperationalError)
            finally:
                self.j._db.execute("ROLLBACK")
            self.assertEqual(self.j.snapshot("run"), before)

            def ambiguous(point):
                if point == "after_commit":
                    raise sqlite3.OperationalError("Injected lost commit acknowledgement")

            other.fault_hook = ambiguous
            with self.assertRaises(JournalUnavailable) as caught:
                other.reserve(operation())
            self.assertEqual(caught.exception.write_outcome, "RECONCILE_REQUIRED")
            other.fault_hook = None
            self.assertEqual(other.reserve(operation()), "ALREADY_RESERVED")
            self.assertEqual(other.snapshot("run").active_reservations, 100)
            self.assertEqual(len(other.events("run")), 2)
            self.assertEqual(other._db.execute("PRAGMA busy_timeout").fetchone()[0], 1000)

    def test_write_admission_fresh_constructors_and_nested_transaction(self):
        ctx = multiprocessing.get_context("spawn")
        start, output = ctx.Event(), ctx.Queue()
        path = Path(self.temp.name) / "fresh.db"
        deadline = time.monotonic() + 10
        children = [
            ctx.Process(target=fresh_admission_worker, args=(str(path), start, output, deadline)) for _ in range(3)
        ]
        try:
            for child in children:
                child.start()
            start.set()
            outcomes = []
            for _ in children:
                try:
                    outcomes.append(output.get(timeout=max(0, deadline - time.monotonic())))
                except queue.Empty:
                    self.fail(
                        f"Fresh constructor outcomes missing: {outcomes}; "
                        f"children={[(child.pid, child.exitcode) for child in children]}"
                    )
            self.assertEqual([item["status"] for item in outcomes], ["OK"] * 3, outcomes)
            self.assertEqual([item["configuration"] for item in outcomes], [self.j.configuration] * 3)
            self.assertEqual({item["pid"] for item in outcomes}, {child.pid for child in children})
            for child in children:
                child.join(max(0, deadline - time.monotonic()))
                self.assertEqual(child.exitcode, 0, outcomes)
        finally:
            for child in children:
                child.join(2)
                if child.is_alive():
                    child.kill()
                    child.join(2)
            output.close()
            output.join_thread()
        with self.j._transaction():
            self.j._db.execute("CREATE TABLE nested_probe(value)")
            with self.assertRaises(JournalUnavailable) as caught:
                with self.j._transaction():
                    self.fail("Nested body executed")
            self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
            self.assertTrue(self.j._db.in_transaction)
        self.assertIsNotNone(self.j._db.execute("SELECT name FROM sqlite_master WHERE name='nested_probe'").fetchone())

    def test_fresh_constructor_unexpected_child_failure_is_attributable(self):
        ctx = multiprocessing.get_context("spawn")
        start, output = ctx.Event(), ctx.Queue()
        deadline = time.monotonic() + 10
        # An existing directory is an invalid database, never a retryable timeout.
        child = ctx.Process(target=fresh_admission_worker, args=(self.temp.name, start, output, deadline))
        try:
            child.start()
            start.set()
            result = output.get(timeout=max(0, deadline - time.monotonic()))
            child.join(max(0, deadline - time.monotonic()))
            self.assertEqual(result["status"], "ERROR", result)
            self.assertEqual(result["pid"], child.pid)
            self.assertEqual(result["attempts"], 1)
            self.assertNotEqual(result["message"], "Write admission deadline expired")
            self.assertTrue(result["errorType"])
            self.assertIsNotNone(child.exitcode)
            self.assertNotEqual(child.exitcode, 0)
        finally:
            if child.is_alive():
                child.kill()
            child.join(2)
            output.close()
            output.join_thread()

    def test_fresh_constructor_does_not_retry_unsafe_or_different_refusal(self):
        start = mock.Mock()
        start.wait.return_value = True
        for message, outcome in (
            ("Write admission deadline expired", "RECONCILE_REQUIRED"),
            ("Database identity changed", "NOT_STARTED"),
        ):
            output = mock.Mock()
            error = JournalUnavailable(message, write_outcome=outcome)
            with self.subTest(message=message), mock.patch(__name__ + ".Journal", side_effect=error) as constructor:
                with self.assertRaises(JournalUnavailable) as caught:
                    fresh_admission_worker("unused.db", start, output)
                self.assertIs(caught.exception, error)
                constructor.assert_called_once()
                result = output.put.call_args.args[0]
                self.assertEqual(result["status"], "ERROR")
                self.assertEqual(result["attempts"], 1)
                self.assertEqual(result["write_outcome"], outcome)
                output.close.assert_called_once()
                output.join_thread.assert_called_once()

    def test_write_admission_alias_refusal_and_symlink_queue(self):
        alias = Path(self.temp.name) / "hardlink.db"
        os.link(self.path, alias)
        before = self.j.snapshot("run")
        try:
            with self.assertRaises(JournalUnavailable):
                Journal(alias, PROOF)
            with self.assertRaises(JournalUnavailable) as caught:
                self.j.reserve(operation())
            self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
            self.assertEqual(self.j.snapshot("run"), before)
        finally:
            alias.unlink()
        if os.name == "posix":
            alias.symlink_to(self.path)
            with Journal(alias, PROOF) as other:
                self.assertEqual(other._queue.directory, self.j._queue.directory)
                self.assertEqual(other._database_identity, self.j._database_identity)
        self.assertEqual(self.j.reserve(operation()), "RESERVED")

    @unittest.skipUnless(hasattr(os, "fork"), "POSIX owner-death/fork witness")
    def test_write_admission_fork_child_cannot_retain_lease(self):
        ready = Path(self.temp.name) / "fork-owner.json"
        child_status = Path(self.temp.name) / "fork-child.json"
        script = (
            "import sys; from tests.accounting.test_journal import fork_lease_owner; fork_lease_owner(*sys.argv[1:])"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(self.path), str(ready), str(child_status)], start_new_session=True
        )
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() or not child_status.exists():
                self.assertIsNone(process.poll(), "Owner died before fixture readiness")
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            owner = json.loads(ready.read_text(encoding="utf-8"))
            child = json.loads(child_status.read_text(encoding="utf-8"))
            self.assertEqual(owner["owner"], process.pid)
            self.assertEqual(owner["child"], child["pid"])
            self.assertTrue(child["inherited_refused"])
            stale_tickets = list(self.j._queue.directory.glob("*-*"))
            self.assertEqual(len(stale_tickets), 1)
            process.kill()
            process.wait(timeout=3)
            self.assertTrue(stale_tickets[0].exists(), "Owner unexpectedly dequeued normally")
            deadline = time.monotonic() + 3
            while not child["orphan"]:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
                child = json.loads(child_status.read_text(encoding="utf-8"))
            os.kill(child["pid"], 0)
            self.assertEqual(self.j.reserve(operation()), "RESERVED")
            progressed = time.monotonic()
            deadline = progressed + 3
            while child["heartbeat"] <= progressed:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
                child = json.loads(child_status.read_text(encoding="utf-8"))
            self.assertTrue(child["orphan"] and child["inherited_refused"])
            self.assertFalse(stale_tickets[0].exists())
            self.assertEqual(self.j.snapshot("run").active_reservations, 100)
            print(
                "FORK_OWNER_DEATH_EVIDENCE",
                json.dumps(
                    {
                        **child,
                        "owner_exit": process.returncode,
                        "stale_ticket_removed": True,
                        "original_reservation": 100,
                    }
                ),
                flush=True,
            )
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)  # Only the fixture's fresh session.
            except ProcessLookupError:
                pass
            process.wait(timeout=3)

    @unittest.skipUnless(os.name == "posix", "Local no-follow-unavailable simulation, not Windows proof")
    def test_write_admission_unsafe_link_refused_before_open(self):
        link = Path(self.temp.name) / "unsafe-guard"
        target = Path(self.temp.name) / "must-not-be-created"
        link.symlink_to(target)
        with mock.patch("agent_lifecycle.accounting.journal.os.O_NOFOLLOW", 0, create=True):
            with mock.patch("agent_lifecycle.accounting.journal.os.open", wraps=os.open) as opened:
                with self.assertRaises(JournalUnavailable) as caught:
                    _Lease(link, os.O_CREAT)
                self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
                opened.assert_not_called()
        self.assertFalse(target.exists())

    def test_write_admission_dead_waiter_and_live_successor(self):
        self._check_dead_waiter_and_live_successor(coordinator_pause=0)

    def test_write_admission_dead_waiter_with_delayed_coordinator(self):
        self._check_dead_waiter_and_live_successor(coordinator_pause=1.2)

    def _check_dead_waiter_and_live_successor(self, coordinator_pause):
        ctx = multiprocessing.get_context("spawn")
        output = ctx.Queue()
        ready, starts = [ctx.Event() for _ in range(2)], [ctx.Event() for _ in range(2)]
        children = [
            ctx.Process(
                target=admission_worker,
                args=(str(self.path), ready[i], starts[i], output, "waiter" + str(i)),
                kwargs={"fixture_queue_seconds": 10.0},
            )
            for i in range(2)
        ]
        try:
            for child in children:
                child.start()
            self.assertTrue(all(event.wait(10) for event in ready))
            with self.j._write_admission():
                deadline = time.monotonic() + 5
                for i in (0, 1):
                    starts[i].set()
                    while len(list(self.j._queue.directory.glob("*-*"))) < i + 2:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.002)
                    if i == 0 and coordinator_pause:
                        time.sleep(coordinator_pause)
                children[0].kill()
                children[0].join(2)
                self.assertFalse(children[0].is_alive())
                self.assertTrue(children[1].is_alive())
            name, result, observation = output.get(timeout=10)
            self.assertEqual((name, result), ("waiter1", "RESERVED"))
            self.assertEqual(observation["status"], "ADMITTED")
            self.assertEqual(observation["product_requested_seconds"], 1.0)
            self.assertEqual(observation["fixture_queue_seconds"], 10.0)
            self.assertEqual(set(self.j._load("run")[0]["operations"]), {"waiter1"})
            self.assertEqual(self.j.snapshot("run").active_reservations, 1)
        finally:
            for child in children:
                child.join(2)
                if child.is_alive():
                    child.kill()
                    child.join(2)
            output.close()
            output.join_thread()

    def test_write_admission_inventory_and_unsafe_entry_refusal(self):
        before = self.j.snapshot("run")
        unknown = self.j._queue.directory / "unexpected"
        unknown.mkdir()
        try:
            with self.assertRaises(JournalUnavailable) as caught:
                self.j.reserve(operation())
            self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
        finally:
            unknown.rmdir()
        leases = []
        try:
            for i in range(64):
                path = self.j._queue.directory / (f"{i:020d}-" + "a" * 32)
                lease = _Lease(path, os.O_CREAT | os.O_EXCL)
                leases.append(lease)
                self.assertTrue(lease.try_lock())
            with self.assertRaises(JournalUnavailable) as caught:
                self.j.reserve(operation())
            self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
            self.assertEqual(self.j.snapshot("run"), before)
        finally:
            for lease in leases:
                lease.close()
                lease.path.unlink()
        self.assertEqual(self.j.reserve(operation()), "RESERVED")

    def test_storage_delta_invalid_record_rolls_back_all_writes(self):
        before = list(self.j._db.iterdump())
        state, revision = self.j._load("run")
        changed = copy.deepcopy(state)
        changed["task_spent"]["task"] = 1
        delta = _state_delta(state, changed)
        delta["result_digest"] = "0" * 64
        with self.assertRaises(JournalUnavailable):
            with self.j._transaction():
                self.j._v2_indexes(
                    [self.j._entry("input_evidence", ["invalid"], "run", "op", {"fixture": True})],
                    [["observed_final", ["source", "bad"], "run", "op", "a" * 64]],
                )
                self.j._record(
                    "run",
                    state,
                    revision,
                    "OBSERVATION_RECORDED",
                    {"state_delta": delta, "indexes": [], "identities": [], "evidence": {}},
                )
        self.assertEqual(list(self.j._db.iterdump()), before)
        self.assertEqual(canonical(self.j._load("run")[0]), canonical(state))

    def test_storage_encoded_event_projection_and_representation_guard(self):
        state, revision = self.j._load("run")
        after = copy.deepcopy(state)
        after["encoding_probe"] = {"юникод": [True, 1, None, '\\"\n']}
        payload = {"state_delta": _state_delta(state, after), "evidence": {"é": True}}
        with self.j._transaction():
            self.j._record("run", state, revision, "OBSERVATION_RECORDED", payload)
        row = self.j._db.execute("SELECT payload,digest FROM events WHERE revision=?", (revision + 1,)).fetchone()
        expected_payload = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        self.assertEqual(row["payload"], expected_payload)
        self.assertEqual(row["digest"], hashlib.sha256(expected_payload.encode("utf-8")).hexdigest())
        expected_state = json.dumps(after, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(
            self.j._db.execute("SELECT data FROM scope_state WHERE scope=?", ("run",)).fetchone()["data"],
            expected_state,
        )
        self.j.rebuild("run")
        self.assertEqual(canonical(self.j._load("run")[0]), expected_state)
        frozen = list(self.j._db.iterdump())
        with self.assertRaises(JournalUnavailable):
            with self.j._transaction():
                self.j._record("run", after, revision + 1, "OBSERVATION_RECORDED", {**payload, "after": after})
        self.assertEqual(list(self.j._db.iterdump()), frozen)

    def test_storage_writer_function_and_transaction_metadata_fence(self):
        before = list(self.j._db.iterdump())
        self.j._db.create_function("alk_storage_writer_version", 0, lambda: 2)
        with self.assertRaises(JournalUnavailable):
            self.j.reserve(operation())
        self.assertEqual(list(self.j._db.iterdump()), before)
        self.j._register_writer(self.j._db)
        self.assertEqual(self.j.reserve(operation()), "RESERVED")
        self.j._db.execute("UPDATE schema_metadata SET version=999")
        before = list(self.j._db.iterdump())
        # Even an otherwise idempotent early return must cross the version check.
        with self.assertRaises(JournalUnavailable):
            self.j.reserve(operation())
        self.assertEqual(list(self.j._db.iterdump()), before)
        with self.assertRaises(JournalUnavailable):
            Journal(self.path, PROOF)

    def test_sv01_configuration_and_unknown_database(self):
        self.assertEqual(self.j.configuration, {"journal_mode": "delete", "synchronous": 2, "foreign_keys": 1})
        other = Path(self.temp.name) / "unrelated.db"
        with closing(sqlite3.connect(other)) as db, db:
            db.execute("CREATE TABLE unrelated(value)")
        with self.assertRaises(JournalUnavailable):
            Journal(other, PROOF)
        with self.assertRaises(JournalUnavailable):
            Journal(":memory:", PROOF)

    def test_explicit_v6_journal_preserves_ordinary_financial_operations(self):
        path = Path(self.temp.name) / "v6.db"
        with Journal(path, PROOF, storage_version=6) as journal:
            self.assertEqual(journal._db.execute("SELECT version FROM schema_metadata").fetchone()[0], 6)
            self.assertEqual(
                journal._db.execute("SELECT migration_id FROM workflow_storage_migrations").fetchone()[0], "init-v6"
            )
            open_scope(journal)
            self.assertEqual(journal.reserve(operation()), "RESERVED")
            before = journal.snapshot("run")
        with self.assertRaises(JournalUnavailable):
            Journal(path, PROOF)  # Unmigrated v5 route cannot silently open v6.
        with Journal(path, PROOF, storage_version=6) as reopened:
            self.assertEqual(reopened.snapshot("run"), before)
            self.assertEqual(reopened.reserve(operation()), "ALREADY_RESERVED")

    def test_sv02_atomic_batch_rollback_and_replay(self):
        before = self.j.snapshot("run")

        def fail(point):
            if point == "after_event":
                raise RuntimeError("injected between event and projection")

        self.j.fault_hook = fail
        with self.assertRaises(RuntimeError):
            self.j.reserve(operation())
        self.j.fault_hook = None
        self.assertEqual(self.j.snapshot("run"), before)
        self.assertEqual(self.j.rebuild("run"), before)
        self.assertEqual(self.j.reserve(operation()), "RESERVED")
        self.assertEqual(self.j.reserve(operation()), "ALREADY_RESERVED")
        self.assertEqual(self.j.snapshot("run").active_reservations, 100)
        committed = self.j.snapshot("run")
        # v4 guards intentional deletion too: inject loss explicitly, then restore the guard.
        trigger = self.j._db.execute(
            "SELECT sql FROM sqlite_master WHERE name='protect_scope_state_delete'"
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.j._db.execute("DELETE FROM scope_state WHERE scope='run'")
        self.j._db.execute("DROP TRIGGER protect_scope_state_delete")
        self.j._db.execute("DELETE FROM scope_state WHERE scope='run'")
        self.j._db.execute(trigger)
        self.assertEqual(self.j.rebuild("run"), committed)
        self.assertEqual(self.j.snapshot("run"), committed)

    def test_sv03_independent_process_writers_and_claim(self):
        ctx = multiprocessing.get_context("spawn")
        for action in ("reserve", "claim"):
            path = Path(self.temp.name) / (action + ".db")
            with Journal(path, PROOF) as journal:
                open_scope(journal, cap=100)
                if action == "claim":
                    journal.reserve(operation())
            barrier, output = ctx.Barrier(2), ctx.Queue()
            workers = [
                ctx.Process(target=concurrent_worker, args=(str(path), barrier, output, action, name))
                for name in ("one", "two")
            ]
            for child in workers:
                child.start()
            results = [output.get(timeout=15) for _ in workers]
            for child in workers:
                child.join(15)
                if child.is_alive():
                    child.terminate()
                    child.join()
                    self.fail("Concurrent worker did not terminate")
                self.assertEqual(child.exitcode, 0)
            output.close()
            with Journal(path, PROOF) as journal:
                if action == "reserve":
                    self.assertEqual(results.count("RESERVED"), 1)
                    self.assertEqual(journal.snapshot("run").active_reservations, 60)
                else:
                    self.assertCountEqual(results, ["CLAIM_GRANTED", "ALREADY_CLAIMED"])

    def test_sv04_dispatch_permit_opening_and_global_source_keys(self):
        for name, change in (
            ("operation", {"upper_bound_tokens": 99}),
            ("dispatch", {"operation_id": "new", "permit_id": "new-permit"}),
            ("permit", {"operation_id": "new", "dispatch_key": "new-dispatch"}),
        ):
            scope = name
            open_scope(self.j, scope)
            op = operation(scope)
            self.j.reserve(op)
            self.assertEqual(self.j.reserve(replace(op, **change)), "CONFLICT")
            self.assertEqual(self.j.snapshot(scope).gate_status, "CONFLICT")
        self.assertEqual(open_scope(self.j), "ALREADY_OPEN")
        self.assertEqual(open_scope(self.j, spent=1), "CONFLICT")
        open_scope(self.j, "first")
        open_scope(self.j, "second")
        one = self.claimed(operation("first"))
        two = self.claimed(operation("second"))
        self.assertEqual(self.j.record_settlement(receipt(one, event="shared")), "SETTLED")
        self.assertEqual(self.j.record_settlement(receipt(two, event="shared")), "CONFLICT")
        self.assertEqual(self.j.snapshot("first").gate_status, "CONFLICT")
        self.assertEqual(self.j.snapshot("second").known_spent, 0)
        self.assertEqual(self.j.snapshot("second").active_reservations, 100)
        self.assertEqual(open_scope(self.j, "covered", covered=(("fixture:source", "shared"),)), "CONFLICT")
        with self.assertRaises(sqlite3.IntegrityError):
            self.j._db.execute("DELETE FROM events")

    def test_sv05_original_ac04(self):
        op = self.claimed()
        value = receipt(op)
        self.assertEqual(self.j.record_settlement(value), "SETTLED")
        self.assertEqual(self.j.record_settlement(value), "ALREADY_SETTLED")
        before = self.j.snapshot("run")
        self.assertEqual((before.spent, before.tasks["task"]["spent"], before.active_reservations), (80, 80, 0))
        self.assertEqual(self.j.record_settlement(replace(value, reported_tokens=81)), "CONFLICT")
        after = self.j.snapshot("run")
        self.assertEqual(after.known_spent, 80)
        self.assertIsNone(after.spent)
        self.assertEqual(after.gate_status, "CONFLICT")

    def test_sv06_process_crash_recovery(self):
        ctx = multiprocessing.get_context("spawn")
        for stage in ("before_commit", "after_claim", "after_settlement"):
            with self.subTest(stage=stage):
                path = Path(self.temp.name) / (stage + ".db")
                with Journal(path, PROOF) as journal:
                    open_scope(journal)
                child = ctx.Process(target=crash_worker, args=(str(path), stage))
                child.start()
                child.join(15)
                if child.is_alive():
                    child.terminate()
                    child.join()
                    self.fail("Crash worker did not terminate")
                self.assertEqual(child.exitcode, 17)
                with Journal(path, PROOF) as journal:
                    projection = journal.rebuild("run")
                    self.assertEqual(projection, journal.snapshot("run"))
                    if stage == "before_commit":
                        self.assertEqual(len(journal.events("run")), 1)
                        self.assertEqual(projection.active_reservations, 0)
                    elif stage == "after_claim":
                        self.assertEqual(projection.active_reservations, 100)
                        self.assertEqual(projection.gate_status, "INCOMPLETE")
                        self.assertEqual(journal.reserve(operation(name="before_host_proof")), "UNAVAILABLE")
                        self.assertEqual(
                            journal.claim("run", "op", operation().binding_digest, "again"), "ALREADY_CLAIMED"
                        )
                        journal.note_unavailable("run", "op", PROOF)
                        self.assertEqual(journal.reserve(operation(name="new")), "UNAVAILABLE")
                        self.assertEqual(journal.record_settlement(receipt(operation())), "SETTLED")
                    else:
                        self.assertEqual(projection.spent, 80)
                        self.assertEqual(journal.record_settlement(receipt(operation())), "ALREADY_SETTLED")

    def test_sv07_original_ac13_and_unknown_history(self):
        task = self.claimed()
        self.j.record_settlement(receipt(task, 80))
        overhead = self.claimed(operation(name="overhead", task=None, upper=20))
        self.j.record_settlement(receipt(overhead, 10))
        p = self.j.snapshot("run")
        self.assertEqual((p.spent, p.tasks["task"]["spent"], p.run_overhead), (90, 80, 10))
        self.assertEqual(p, self.j.rebuild("run"))
        open_scope(self.j, "unknown", spent=None, pending=None)
        unknown = self.j.snapshot("unknown")
        self.assertIsNone(unknown.spent)
        self.assertIsNone(unknown.active_reservations)
        self.assertEqual(self.j.reserve(operation("unknown")), "UNAVAILABLE")
        open_scope(self.j, "past", spent=40, overhead=10, covered=(("fixture:source", "already-covered"),))
        past = self.claimed(operation("past"))
        self.assertEqual(self.j.record_settlement(receipt(past, event="already-covered")), "CONFLICT")
        self.assertEqual(self.j.snapshot("past").known_spent, 50)

    def test_sv08_closeout_unused_reservation(self):
        for scope, cancel in (("settle", False), ("cancel", True)):
            open_scope(self.j, scope, protected={"task": 40, "": 20})
            op = operation(scope, upper=25, closeout=True)
            self.j.reserve(op)
            reserved = self.j.snapshot(scope)
            self.assertEqual((reserved.active_reservations, reserved.protected_closeout), (25, 35))
            if cancel:
                self.assertEqual(self.j.cancel_without_dispatch(scope, "op", PROOF), "CANCELLED")
                expected = (0, 60, 40)
                self.assertEqual(self.j.claim(scope, "op", op.binding_digest, "late"), "DENY")
            else:
                self.j.claim(scope, "op", op.binding_digest, "claim")
                self.j.record_settlement(receipt(op, 20))
                expected = (20, 40, 20)
            p = self.j.snapshot(scope)
            self.assertEqual((p.spent, p.protected_closeout, p.tasks["task"]["protected_closeout"]), expected)
            self.assertEqual(p.active_reservations, 0)

    def test_sv09_integer_schema_and_oversized_actual(self):
        self.assertEqual(uint(0), 0)
        self.assertEqual(uint(MAX_INTEGER), MAX_INTEGER)
        for value in (True, 1.0, -1, MAX_INTEGER + 1):
            with self.assertRaises(ValueError):
                uint(value)
        with self.assertRaises(ValueError):
            canonical({"amount": 1.0})
        policy = BudgetPolicy("policy", 1, 100, {"task": 100}, {"task": 10}, PROOF)
        policy.protected_closeout["task"] = -1
        with self.assertRaises(ValueError):
            self.j.open_scope(
                BudgetScope("mutated", "mutated", "reportedTokens:fixture:v1"),
                policy,
                OpeningBalance("opening", "source", "reportedTokens:fixture:v1", {"task": 0}, 0, (), PROOF, PROOF),
            )
        with self.assertRaises(ValueError):
            BudgetPolicy("policy", 1, MAX_INTEGER, {"task": MAX_INTEGER}, {"task": MAX_INTEGER, "": 1}, PROOF)
        op = self.claimed()
        value = receipt(op, MAX_INTEGER + 1)
        self.assertEqual(self.j.record_settlement(value), "UNAVAILABLE")
        self.assertIn(str(MAX_INTEGER + 1), self.j.events("run")[-1]["payload"])
        p = self.j.snapshot("run")
        self.assertIsNone(p.spent)
        self.assertEqual(p.active_reservations, 100)
        self.assertEqual(p.gate_status, "BOUND_BROKEN")
        self.assertEqual(p, self.j.rebuild("run"))
        other = Path(self.temp.name) / "future.db"
        with Journal(other, PROOF):
            pass
        with closing(sqlite3.connect(other)) as db, db:
            db.execute("UPDATE schema_metadata SET version=999")
        with self.assertRaises(JournalUnavailable):
            Journal(other, PROOF)

    def test_f01_sticky_gate_survives_other_operation_resolution(self):
        for blocker in ("BOUND_BROKEN", "CONFLICT"):
            for uncertainty in ("note", "rebuild"):
                for resolution in ("settle", "cancel"):
                    with self.subTest(blocker=blocker, uncertainty=uncertainty, resolution=resolution):
                        scope = f"f01-{blocker}-{uncertainty}-{resolution}"
                        open_scope(self.j, scope)
                        a = self.claimed(operation(scope, name="A", upper=25))
                        b = self.claimed(operation(scope, name="B", upper=10))
                        waiting = operation(scope, name="waiting", upper=1)
                        self.assertEqual(self.j.reserve(waiting), "RESERVED")
                        actual_a = 30 if blocker == "BOUND_BROKEN" else 20
                        a_receipt = receipt(a, actual_a)
                        expected_a = "SETTLED_BOUND_BROKEN" if blocker == "BOUND_BROKEN" else "SETTLED"
                        self.assertEqual(self.j.record_settlement(a_receipt), expected_a)
                        if blocker == "CONFLICT":
                            self.assertEqual(
                                self.j.record_settlement(replace(a_receipt, reported_tokens=21)), "CONFLICT"
                            )
                        evidence_before = self.j.events(scope)
                        self.assertEqual(self.j.snapshot(scope).gate_status, blocker)
                        if uncertainty == "note":
                            self.assertEqual(self.j.note_unavailable(scope, "B", PROOF), "RECORDED")
                        else:
                            self.j.rebuild(scope)
                        gate_while_uncertain = self.j.snapshot(scope).gate_status
                        self.assertEqual(self.j.snapshot(scope).active_reservations, 11)
                        if resolution == "settle":
                            result = self.j.record_settlement(receipt(b, 10))
                            self.assertEqual(result, "SETTLED")

                            def duplicate(op=b):
                                return self.j.record_settlement(receipt(op, 10))

                            expected_duplicate = "ALREADY_SETTLED"
                            expected_spent = actual_a + 10
                        else:
                            result = self.j.cancel_without_dispatch(scope, "B", PROOF)
                            self.assertEqual(result, "CANCELLED")

                            def duplicate(budget_scope=scope):
                                return self.j.cancel_without_dispatch(budget_scope, "B", PROOF)

                            expected_duplicate = "ALREADY_CANCELLED"
                            expected_spent = actual_a
                        after = self.j.snapshot(scope)
                        self.assertEqual(duplicate(), expected_duplicate)
                        self.assertEqual(self.j.snapshot(scope), after)
                        replayed = self.j.rebuild(scope)
                        self.assertEqual(replayed, after)
                        self.assertEqual(replayed.known_spent, expected_spent)
                        self.assertEqual(replayed.tasks["task"]["known_spent"], expected_spent)
                        self.assertEqual(replayed.active_reservations, 1)
                        if blocker == "CONFLICT":
                            self.assertIsNone(replayed.spent)
                        else:
                            self.assertEqual(replayed.spent, expected_spent)
                        history = self.j.events(scope)
                        self.assertEqual(history[: len(evidence_before)], evidence_before)
                        a_charges = [
                            json.loads(event["payload"])["receipt"]["reported_tokens"]
                            for event in history
                            if event["kind"] == "SETTLE" and json.loads(event["payload"])["operation_id"] == "A"
                        ]
                        self.assertEqual(a_charges, [actual_a])
                        self.assertEqual(
                            (gate_while_uncertain, after.gate_status, replayed.gate_status),
                            (blocker, blocker, blocker),
                        )
                        self.assertEqual(self.j.reserve(operation(scope, name="new", upper=1)), "UNAVAILABLE")
                        self.assertEqual(
                            self.j.claim(scope, "waiting", waiting.binding_digest, "must-not-dispatch"), "DENY"
                        )

    def test_f01_normal_uncertainty_resolves_without_sticky_blocker(self):
        for uncertainty in ("note", "rebuild"):
            for resolution in ("settle", "cancel"):
                with self.subTest(uncertainty=uncertainty, resolution=resolution):
                    scope = f"f01-normal-{uncertainty}-{resolution}"
                    open_scope(self.j, scope)
                    op = self.claimed(operation(scope, upper=10))
                    if uncertainty == "note":
                        self.j.note_unavailable(scope, "op", PROOF)
                    else:
                        self.j.rebuild(scope)
                    self.assertEqual(self.j.snapshot(scope).gate_status, "INCOMPLETE")
                    if resolution == "settle":
                        self.assertEqual(self.j.record_settlement(receipt(op, 10)), "SETTLED")
                    else:
                        self.assertEqual(self.j.cancel_without_dispatch(scope, "op", PROOF), "CANCELLED")
                    projection = self.j.rebuild(scope)
                    self.assertEqual(projection.gate_status, "READY")
                    self.assertEqual(projection.active_reservations, 0)
                    self.assertEqual(projection.spent, 10 if resolution == "settle" else 0)
                    self.claimed(operation(scope, name="new", upper=1))

    def test_f01_conflict_survives_another_bound_violation_or_overflow(self):
        for actual in (11, MAX_INTEGER + 1):
            with self.subTest(actual=actual):
                scope = f"f01-conflict-{actual}"
                open_scope(self.j, scope)
                a = self.claimed(operation(scope, name="A", upper=25))
                b = self.claimed(operation(scope, name="B", upper=10))
                self.j.record_settlement(receipt(a, 20))
                self.assertEqual(self.j.record_settlement(receipt(a, 21)), "CONFLICT")
                self.j.record_settlement(receipt(b, actual))
                gate_after_charge = self.j.snapshot(scope).gate_status
                projection = self.j.rebuild(scope)
                self.assertEqual((gate_after_charge, projection.gate_status), ("CONFLICT", "CONFLICT"))
                self.assertIsNone(projection.spent)
                self.assertEqual(projection.known_spent, 31 if actual == 11 else 20)
                self.assertEqual(projection.active_reservations, 0 if actual == 11 else 10)
                history = self.j.events(scope)
                self.assertTrue(any(event["kind"] == "CONFLICT" for event in history))
                if actual > MAX_INTEGER:
                    overflow = next(event for event in history if event["kind"] == "OVERFLOW")
                    self.assertEqual(json.loads(overflow["payload"])["receipt"]["reported_tokens"], actual)
                self.assertEqual(self.j.reserve(operation(scope, name="new", upper=1)), "UNAVAILABLE")

    def test_bound_break_full_actual_and_durable_unknown(self):
        op = self.claimed(operation(upper=25))
        self.assertEqual(self.j.record_settlement(receipt(op, 30)), "SETTLED_BOUND_BROKEN")
        self.assertEqual(self.j.snapshot("run").spent, 30)
        self.assertEqual(self.j.reserve(operation(name="after")), "UNAVAILABLE")
        self.assertEqual(self.j.rebuild("run").gate_status, "BOUND_BROKEN")

    def test_revision_and_checked_reservation_sum(self):
        with self.assertRaises(RevisionConflict):
            self.j.reserve(operation(), expected_revision=0)
        self.assertEqual(self.j.snapshot("run").journal_revision, 1)
        open_scope(self.j, "max", cap=MAX_INTEGER, spent=MAX_INTEGER)
        with self.assertRaises(ValueError):
            self.j.reserve(operation("max", upper=1))
        self.assertEqual(self.j.snapshot("max").known_spent, MAX_INTEGER)

    def test_cap_equality_and_task_attribution(self):
        open_scope(self.j, "equal", cap=100)
        self.assertEqual(self.j.reserve(operation("equal", upper=100)), "RESERVED")
        self.assertEqual(self.j.reserve(operation("equal", name="extra", upper=1)), "DENY")
        with self.assertRaises(ValueError):
            replace(operation(), task_id=None)


class BoundedPrefixTests(unittest.TestCase):
    def test_complete_exact_caps_and_read_only_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal)
                first = journal.bounded_prefix(
                    "run",
                    expected_revision=1,
                    boundary=(1, 0),
                    max_rows=1,
                    max_bytes=1 << 20,
                )
                exact = journal.bounded_prefix(
                    "run",
                    expected_revision=1,
                    boundary=(1, 0),
                    max_rows=1,
                    max_bytes=first["utf8Bytes"],
                )
                self.assertEqual(first, exact)
                self.assertEqual(exact["rowCount"], 1)
                self.assertEqual(journal.snapshot("run").journal_revision, 1)
                self.assertEqual(exact["prefixDigest"], digest({k: v for k, v in exact.items() if k != "prefixDigest"}))

    def test_payload_is_not_loaded_after_utf8_or_row_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal)
                journal.reserve(replace(operation(), attribution_reason="é" * 5000))
                for rows, byte_limit in ((1, 1 << 20), (2, 6000)):
                    trace = []
                    journal._db.set_trace_callback(trace.append)
                    try:
                        with self.assertRaises(JournalUnavailable):
                            journal.bounded_prefix(
                                "run",
                                expected_revision=2,
                                boundary=(2, 0),
                                max_rows=rows,
                                max_bytes=byte_limit,
                            )
                    finally:
                        journal._db.set_trace_callback(None)
                    self.assertFalse(any("SELECT * FROM events" in sql for sql in trace))

    def test_missing_scope_invalid_caps_and_drifting_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal)
                for rows, byte_limit in ((0, 1), (True, 1), (4097, 1), (1, 0), (1, 16777217)):
                    with self.assertRaises(ValueError):
                        journal.bounded_prefix(
                            "run",
                            expected_revision=1,
                            boundary=(1, 0),
                            max_rows=rows,
                            max_bytes=byte_limit,
                        )
                with self.assertRaises(JournalUnavailable):
                    journal.bounded_prefix(
                        "absent",
                        expected_revision=0,
                        boundary=(0, 0),
                        max_rows=1,
                        max_bytes=1000,
                    )
                with self.assertRaises(JournalUnavailable):
                    journal.bounded_prefix(
                        "run",
                        expected_revision=1,
                        boundary=(1, 1),
                        max_rows=1,
                        max_bytes=10000,
                    )
                journal.reserve(operation())
                with self.assertRaises(RevisionConflict):
                    journal.bounded_prefix(
                        "run",
                        expected_revision=1,
                        boundary=(1, 0),
                        max_rows=2,
                        max_bytes=10000,
                    )


class StateDeltaTests(unittest.TestCase):
    def test_storage_encoded_replay_preserves_typed_bytes_and_isolation(self):
        before = {"kept": {"array": [True, 1]}, "value": True}
        after = {"kept": {"array": [True, 1]}, "value": 1, "é": ['\\"\n', None]}
        encoded_after = json.dumps(after, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        patch = _state_delta(before, after)
        result, encoded = _apply_delta_encoded(before, patch)
        self.assertEqual(encoded, encoded_after)
        self.assertEqual(hashlib.sha256(encoded.encode("utf-8")).hexdigest(), patch["result_digest"])
        result["kept"]["array"][0] = False
        result["é"][0] = "changed"
        self.assertIs(before["kept"]["array"][0], True)
        self.assertEqual(patch["changes"][-1]["value"][0], '\\"\n')
        self.assertEqual(encoded, encoded_after)
        before["kept"]["array"].append("later")
        self.assertEqual(encoded, encoded_after)

    def test_storage_delta_independent_nested_oracle_and_immutable_input(self):
        before = {
            "": {"flag": True, "keep": ""},
            "arr": [True, {"a": 1}],
            "gone": {"old": 9},
            "nested": {"a": 1, "b": None},
            "untouched": {"operation": {"original_cost": 999}},
        }
        after = {
            "": {"flag": 1, "keep": ""},
            "arr": [1, {"a": True}],
            "nested": {"a": "1", "b": None, "z": False},
            "new": {"zero": 0},
            "untouched": {"operation": {"original_cost": 999}},
        }
        changes = [
            {"op": "replace", "path": ["", "flag"], "value": 1},
            {"op": "replace", "path": ["arr"], "value": [1, {"a": True}]},
            {"op": "remove", "path": ["gone"]},
            {"op": "replace", "path": ["nested", "a"], "value": "1"},
            {"op": "add", "path": ["nested", "z"], "value": False},
            {"op": "add", "path": ["new"], "value": {"zero": 0}},
        ]
        patch = {
            "codec": "ALK_STATE_DELTA_V1",
            "base_digest": digest(before),
            "result_digest": digest(after),
            "changes": changes,
        }
        encoded_before = canonical(before)
        self.assertEqual(canonical(_state_delta(before, after)), canonical(patch))
        result = _apply_delta(before, patch)
        self.assertEqual(canonical(result), canonical(after))
        self.assertEqual(canonical(before), encoded_before)
        self.assertNotIn("untouched", canonical(patch))
        result["untouched"]["operation"]["original_cost"] = 0
        self.assertEqual(canonical(before), encoded_before)
        self.assertEqual(_state_delta(after, after)["changes"], [])
        initial = {
            "codec": "ALK_STATE_DELTA_V1",
            "base_digest": digest(None),
            "result_digest": digest(after),
            "changes": [{"op": "initialize", "path": [], "value": after}],
        }
        self.assertEqual(canonical(_state_delta(None, after)), canonical(initial))
        self.assertEqual(canonical(_apply_delta(None, initial)), canonical(after))

    def test_storage_delta_malformed_records_fail_without_input_mutation(self):
        before = {"a": {"b": 1}, "array": [1], "z": None}
        good = {
            "codec": "ALK_STATE_DELTA_V1",
            "base_digest": digest(before),
            "result_digest": digest(before),
            "changes": [],
        }
        bad = [
            None,
            [],
            {**good, "extra": 1},
            {**good, "codec": "unknown"},
            {**good, "base_digest": "0" * 64},
            {**good, "result_digest": "0" * 64},
            {**good, "changes": {}},
            {**good, "changes": [None]},
        ]
        change_sets = [
            [{"op": "unknown", "path": ["x"], "value": 1}],
            [{"op": [], "path": ["x"], "value": 1}],
            [{"op": "add", "path": ["x"], "value": 1, "extra": 0}],
            [{"op": "add", "path": ["x"]}],
            [{"op": "remove", "path": ["z"], "value": 0}],
            [{"op": "add", "path": "x", "value": 1}],
            [{"op": "add", "path": [1], "value": 1}],
            [{"op": "add", "path": ["x"], "value": 1.5}],
            [{"op": "add", "path": ["a"], "value": 1}],
            [{"op": "replace", "path": ["missing"], "value": 1}],
            [{"op": "remove", "path": ["missing"]}],
            [{"op": "add", "path": ["missing", "x"], "value": 1}],
            [{"op": "add", "path": ["array", "0"], "value": 1}],
            [{"op": "replace", "path": [], "value": {}}],
            [{"op": "remove", "path": []}],
            [{"op": "initialize", "path": [], "value": {}}],
            [{"op": "replace", "path": ["z"], "value": 1}, {"op": "replace", "path": ["a"], "value": 2}],
            [{"op": "remove", "path": ["a"]}, {"op": "remove", "path": ["a"]}],
            [{"op": "replace", "path": ["a"], "value": {}}, {"op": "add", "path": ["a", "b"], "value": 2}],
        ]
        bad.extend({**good, "changes": changes} for changes in change_sets)
        frozen = canonical(before)
        for index, patch in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(JournalUnavailable):
                _apply_delta(before, patch)
            self.assertEqual(canonical(before), frozen)
        for changes in (
            [],
            [{"op": "add", "path": [], "value": {}}],
            [{"op": "initialize", "path": [], "value": []}],
            [{"op": "initialize", "path": ["x"], "value": {}}],
        ):
            with self.subTest(initial=changes), self.assertRaises(JournalUnavailable):
                _apply_delta(None, {**good, "base_digest": digest(None), "changes": changes})
        for payload in ({}, {"after": before, "state_delta": good}, {"after": []}):
            with self.subTest(payload=payload), self.assertRaises(JournalUnavailable):
                _apply(before, "OBSERVATION_RECORDED", payload)


if __name__ == "__main__":
    unittest.main()
