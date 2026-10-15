"""D-RESOURCE reconstruction examples; fixture records grant no financial authority."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_lifecycle.accounting.closing_resource_recovery import (
    _read_current_closing_resource_data,
    _resolve_native_operation_data,
    read_persisted_closing_balances,
    reconstruct_closing_balances,
)
from agent_lifecycle.accounting.contracts import BudgetPolicy, EvidenceRef, JournalUnavailable, canonical, digest
from agent_lifecycle.contracts.errors import LifecycleError
from tests.accounting.test_journal import operation


def _limit(kind: str, task: str | None, spent: int, additional: int | None) -> dict:
    return {
        "scope": {"scopeKind": kind, "taskId": task},
        "participation": "CLOSING_ENABLED" if additional is not None else "RETAIN_ONLY",
        "oldCap": {"kind": "FINITE", "value": 100},
        "knownSpentAtAnchor": spent,
        "approvedAdditional": additional,
        "prospectiveCumulativeCeiling": spent + additional if additional is not None else None,
        "capDisposition": "SUPERSEDE_BY_CLOSING_POLICY" if additional is not None else "RETAIN_BINDING",
        "priorViolationSetDigest": "a" * 64,
    }


def _operation(operation_id: str, task: str | None, upper: int, actual: int | None) -> dict:
    binding = {
        "operation_id": operation_id, "budget_scope_id": "scope", "run_id": "run",
        "task_id": task, "unit_definition_id": "unit", "upper_bound_tokens": upper,
    }
    return {
        "binding": binding, "digest": digest(binding),
        "state": "SETTLED" if actual is not None else "RESERVED",
        "reservation": 0 if actual is not None else upper, "actual": actual,
    }


def _sidecar(operation_id: str, owner: str | None, native: dict) -> dict:
    return {
        "schemaVersion": "agent-closing-operation-binding.v1",
        "bindingId": "binding", "runId": "run", "budgetScopeId": "scope",
        "closingWindowId": "window", "policyEffectDigest": "b" * 64,
        "operationId": operation_id, "nativeOperationRef": {"path": "op.json", "sha256": "c" * 64, "bytes": 1},
        "nativeOperationDigest": native["digest"], "action": "accounting-closeout",
        "owner": {"scopeKind": "TASK" if owner else "RUN", "taskId": owner},
        "unit": {"metric": "reportedTokens", "unitDefinitionId": "unit",
                 "definitionDigest": "d" * 64, "sourceQualificationDigest": "e" * 64},
        "upperBound": native["binding"]["upper_bound_tokens"],
        "expectedJournalRevision": 1, "expectedWorkflowRevision": 1,
        "expectedAuthorityEpoch": 0, "expectedGuardStateDigest": "f" * 64,
    }


def _bucket(owner: str | None, origin: str, amount: int) -> dict:
    return {
        "schemaVersion": "agent-closing-protection-bucket.v1", "budgetScopeId": "scope",
        "owner": {"scopeKind": "TASK" if owner else "RUN", "taskId": owner},
        "originWindowId": origin, "unspent": amount,
    }


def _example() -> tuple[dict, dict, list[dict], list[dict]]:
    old = _operation("old-late", None, 5, 5)
    current = _operation("task-current", "task", 4, 3)
    reserved = _operation("run-closeout", None, 8, None)
    state = {
        "scope": {"budget_scope_id": "scope", "run_id": "run", "unit_definition_id": "unit"},
        "opening": {"pending_operations": []},
        "task_spent": {"task": 3}, "overhead": 95,
        "operations": {"old-late": old, "task-current": current, "run-closeout": reserved},
        "protected": {"": 6, "task": 4}, "qualified": True, "gate": "READY",
    }
    proposal = {
        "schemaVersion": "agent-closing-resource-proposal.v1", "runId": "run",
        "budgetScopeId": "scope", "bindingId": "binding", "closingWindowId": "window",
        "unit": {"metric": "reportedTokens", "unitDefinitionId": "unit",
                 "definitionDigest": "d" * 64, "sourceQualificationDigest": "e" * 64},
        "limits": [_limit("RUN", None, 90, 30), _limit("TASK", "task", 0, 10)],
    }
    sidecars = [_sidecar("task-current", "task", current), _sidecar("run-closeout", None, reserved)]
    buckets = [_bucket(None, "legacy", 4), _bucket(None, "window", 2),
               _bucket("task", "window", 4)]
    return state, proposal, sidecars, buckets


class ClosingRecoveryTests(unittest.TestCase):
    def test_current_window_data_join_uses_same_sql_effect_and_financial_rows(self) -> None:
        db, binding = self._persisted_example()
        try:
            effect_digest = db.execute(
                "SELECT effect_digest FROM closing_policy_effects WHERE run_id='run' AND closing_window_id='window'"
            ).fetchone()[0]
            current = {'state': {'closingWindow': {
                'closingWindowId': 'window', 'resourcePolicyEffectDigest': effect_digest,
            }}}
            result = _read_current_closing_resource_data(db, binding, current, 'window')
            self.assertEqual(result['status'], 'CURRENT')
            self.assertIs(result['financialAdmission'], False)
            with self.assertRaises(JournalUnavailable):
                _read_current_closing_resource_data(db, binding, current, 'retired-window')
            changed = {'state': {'closingWindow': {
                'closingWindowId': 'window', 'resourcePolicyEffectDigest': '0' * 64,
            }}}
            with self.assertRaises(JournalUnavailable):
                _read_current_closing_resource_data(db, binding, changed, 'window')
        finally:
            db.close()

    def test_native_operation_artifact_data_matches_sidecar_without_authority(self) -> None:
        native = operation('scope', name='native', task='task', upper=7)
        data = asdict(native)
        raw = canonical(data).encode('utf-8')
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            path = root / 'operation.json'
            path.write_bytes(raw)
            sidecar = _sidecar('native', 'task', {'binding': {'upper_bound_tokens': 7},
                                                  'digest': native.binding_digest})
            sidecar['runId'] = native.run_id
            sidecar['unit']['unitDefinitionId'] = native.unit_definition_id
            sidecar['nativeOperationRef'] = {
                'path': 'operation.json', 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            }
            self.assertEqual(_resolve_native_operation_data(root, sidecar), native)
            changed_ref = copy.deepcopy(sidecar)
            changed_ref['nativeOperationRef']['sha256'] = '0' * 64
            with self.assertRaises(LifecycleError):
                _resolve_native_operation_data(root, changed_ref)
            changed_data = {**data, 'operation_id': 'different'}
            changed_raw = canonical(changed_data).encode('utf-8')
            path.write_bytes(changed_raw)
            changed_ref['nativeOperationRef'] = {
                'path': 'operation.json', 'sha256': hashlib.sha256(changed_raw).hexdigest(), 'bytes': len(changed_raw),
            }
            with self.assertRaises(LifecycleError):
                _resolve_native_operation_data(root, changed_ref)
            outside_path = Path(outside) / 'operation.json'
            outside_path.write_bytes(raw)
            path.unlink()
            path.symlink_to(outside_path)
            with self.assertRaises(LifecycleError):
                _resolve_native_operation_data(root, sidecar)

    @staticmethod
    def _persisted_example() -> tuple[sqlite3.Connection, dict]:
        state, proposal, sidecars, buckets = _example()
        before_native = asdict(BudgetPolicy("policy", 1, 100, {"task": 10}, {"": 4, "task": 4},
                                            EvidenceRef("prior", "a" * 64)))
        proposal.update(expectedJournalRevision=6, journalIdentity="journal", inventoryDigest="1" * 64)
        proposal_digest = digest(proposal)
        after_native = asdict(BudgetPolicy(
            "policy", 2, 120, {"task": 10}, {"": 6, "task": 4},
            EvidenceRef("urn:alk:closing-resource-proposal:" + proposal_digest, proposal_digest),
        ))
        state["policy"] = after_native
        after = {"policyId": "policy", "revision": 2, "policyDigest": digest(after_native)}
        before = {"policyId": "policy", "revision": 1, "policyDigest": digest(before_native)}
        candidate = {
            "schemaVersion": "agent-closing-resource-candidate.v1",
            "proposalDigest": digest(proposal), "bindingId": "binding", "runId": "run",
            "budgetScopeId": "scope", "journalIdentity": "journal", "closingWindowId": "window",
            "inventoryDigest": proposal["inventoryDigest"], "expectedJournalRevision": 6,
            "beforePolicy": before, "afterPolicy": after,
        }
        effect = {
            "schemaVersion": "agent-closing-resource-effect.v1", "runId": "run",
            "budgetScopeId": "scope", "closingWindowId": "window", "beforeJournalRevision": 6,
            "afterJournalRevision": 7, "beforePolicy": before, "afterPolicy": after,
            "proposalDigest": digest(proposal), "candidateDigest": digest(candidate),
            "activationOperationId": "synthetic-activation", "authorityDecisionDigest": "a" * 64,
            "grantDigest": "b" * 64,
        }
        for sidecar in sidecars:
            sidecar["policyEffectDigest"] = digest(effect)
        record = {"effect": effect, "candidate": candidate, "proposal": proposal,
                  "nativeBeforePolicy": before_native, "nativeAfterPolicy": after_native}
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE closing_policy_effects(run_id TEXT,closing_window_id TEXT,effect_digest TEXT,payload TEXT);
            CREATE TABLE events(scope TEXT,revision INTEGER,ordinal INTEGER,kind TEXT,payload TEXT,digest TEXT);
            CREATE TABLE scope_state(scope TEXT,revision INTEGER,data TEXT);
            CREATE TABLE closing_operation_bindings(budget_scope_id TEXT,operation_id TEXT,binding_digest TEXT,payload TEXT);
            CREATE TABLE closing_protection_buckets(budget_scope_id TEXT,owner TEXT,origin_window_id TEXT,generation INTEGER,payload TEXT);
            CREATE TABLE closing_resource_balances(budget_scope_id TEXT,closing_window_id TEXT,owner TEXT,generation INTEGER,payload TEXT);
        """)
        db.execute("INSERT INTO closing_policy_effects VALUES(?,?,?,?)", ("run", "window", digest(effect), canonical(record)))
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", ("scope", 7, 0, "CLOSING_POLICY_APPLIED", canonical(record), digest(record)))
        db.execute("INSERT INTO scope_state VALUES(?,?,?)", ("scope", 7, canonical(state)))
        for sidecar in sidecars:
            db.execute("INSERT INTO closing_operation_bindings VALUES(?,?,?,?)",
                       ("scope", sidecar["operationId"], digest(sidecar), canonical(sidecar)))
        for bucket in buckets:
            owner = bucket["owner"]["taskId"] or ""
            db.execute("INSERT INTO closing_protection_buckets VALUES(?,?,?,?,?)",
                       ("scope", owner, bucket["originWindowId"], 7, canonical(bucket)))
        for row in reconstruct_closing_balances(state, 7, proposal, sidecars, buckets, digest(effect)):
            db.execute("INSERT INTO closing_resource_balances VALUES(?,?,?,?,?)",
                       ("scope", "window", row["scope"]["taskId"] or "", 7, canonical(row)))
        return db, {"runId": "run", "budgetScopeId": "scope", "bindingId": "binding",
                    "journalIdentity": "journal"}

    def test_persisted_digest_chain_and_projection_reconcile_without_grant(self) -> None:
        db, binding = self._persisted_example()
        try:
            result = read_persisted_closing_balances(db, binding, "window")
            self.assertEqual(result["status"], "CURRENT")
            self.assertIs(result["financialAdmission"], False)
            db.execute("UPDATE closing_resource_balances SET generation=6 WHERE owner='task'")
            self.assertEqual(read_persisted_closing_balances(db, binding, "window")["status"], "REBUILD_REQUIRED")
            db.execute("UPDATE closing_resource_balances SET generation=7,payload='{}' WHERE owner='task'")
            with self.assertRaises(LifecycleError):
                read_persisted_closing_balances(db, binding, "window")
        finally:
            db.close()

    def test_late_old_spend_consumes_global_without_minting_window_allowance(self) -> None:
        state, proposal, sidecars, buckets = _example()
        rows = reconstruct_closing_balances(state, 7, proposal, sidecars, buckets, "b" * 64)
        run, task = rows
        self.assertEqual(run["currentCumulativeSpent"], 98)
        self.assertEqual(run["windowSpent"], 3)
        self.assertEqual(run["windowActiveReservations"], 8)
        self.assertEqual(run["globalProtected"], 10)
        self.assertEqual(run["windowProtected"], 6)
        self.assertEqual(run["cumulativeCeiling"], 120)
        self.assertEqual(run["windowAllowance"], 30)
        self.assertEqual(task["currentCumulativeSpent"], 3)
        self.assertEqual(task["windowSpent"], 3)
        self.assertEqual(task["windowActiveReservations"], 0)
        self.assertNotIn("financialAdmission", run)

    def test_duplicate_or_relabelled_operation_cannot_increase_or_hide_window_cost(self) -> None:
        state, proposal, sidecars, buckets = _example()
        for changed in (sidecars + sidecars[:1],
                        [{**sidecars[0], "owner": {"scopeKind": "RUN", "taskId": None}}, sidecars[1]],
                        [{**sidecars[0], "nativeOperationDigest": "0" * 64}, sidecars[1]]):
            with self.subTest(changed=changed), self.assertRaises(LifecycleError):
                reconstruct_closing_balances(state, 7, proposal, changed, buckets, "b" * 64)

    def test_bucket_conservation_and_retained_task_are_fail_closed(self) -> None:
        state, proposal, sidecars, buckets = _example()
        changed = copy.deepcopy(buckets)
        changed[1]["unspent"] += 1
        with self.assertRaises(LifecycleError):
            reconstruct_closing_balances(state, 7, proposal, sidecars, changed, "b" * 64)
        retained = copy.deepcopy(proposal)
        retained["limits"][1] = _limit("TASK", "task", 0, None)
        with self.assertRaises(LifecycleError):
            reconstruct_closing_balances(state, 7, retained, sidecars, buckets, "b" * 64)

    def test_unknown_native_protection_is_never_zero(self) -> None:
        state, proposal, sidecars, buckets = _example()
        state["protected"]["task"] = None
        with self.assertRaises(LifecycleError):
            reconstruct_closing_balances(state, 7, proposal, sidecars, buckets, "b" * 64)


class RawRetentionWitnessTests(unittest.TestCase):
    """Temporary private local journal witnesses; no native or scheduled-target claim."""

    def setUp(self):
        from agent_lifecycle.accounting.journal import Journal
        from tests.accounting.test_journal import PROOF
        from tests.accounting.test_normalization import observation
        from tests.accounting.test_opening_balances import import_data, paid

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal_path = self.root / "journal.db"
        self.proof = PROOF
        self.clock_now = datetime.now(UTC)
        self.j = Journal(self.journal_path, PROOF, utc_clock=lambda: self.clock_now)
        self.journal_path.chmod(0o600)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: self.j.close())
        self.assertEqual(self.j.import_opening(*import_data()).status, "IMPORTED")
        self.op = paid(self.j, operation())
        self.original = observation([self.op], [10], event="original-raw-retention")
        self.assertEqual(self.j.ingest_usage("run", self.original).status, "SETTLED")
        manifest = Path("tasks/release-2-16/plan.manifest.json").read_bytes()
        lock = Path("tasks/release-2-16/plan.lock.json").read_bytes()
        self.manifest = self._write("plan/manifest.json", manifest)
        self.lock = self._write("plan/lock.json", lock)
        self.authority = {
            "schemaVersion": "alk-r68b-maintenance-authority.v1",
            "rootPathSha256": hashlib.sha256(os.fsencode(str(self.root))).hexdigest(),
            "rootFileIdentity": self._file_id(self.root),
            "journalPath": "journal.db", "journalFileIdentity": self._file_id(self.journal_path),
            "journalIdentity": self.j.journal_identity, "storageVersion": self.j._storage_version,
            "writerDigest": digest(asdict(PROOF)), "planDigest": digest(json.loads(manifest)),
            "manifestRef": self.manifest, "lockRef": self.lock, "allowedAction": "RAW_RETENTION",
        }
        self.authority_ref = self._write("maintenance-authority.json", canonical(self.authority).encode())
        self.sources = {}

    def _file_id(self, path):
        info = path.lstat()
        return {"device": info.st_dev, "inode": info.st_ino}

    def _write(self, path, raw):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(raw)
        target.chmod(0o600)
        return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def _seal(self, attempt="attempt-1", *, operation_id=None):
        prefix = attempt if operation_id is None else attempt + "/operations/" + digest({"operationId": operation_id})
        parent = self.root
        for part in Path(prefix).parts:
            parent = parent / part
            parent.mkdir(mode=0o700, exist_ok=True)
        entries = []
        for name, kind in (("input-request.json", "sealed-request"), ("prompt-input.json", "diagnostic"),
                           ("effective-config.json", "effective-config")):
            ref = self._write(prefix + "/" + name, (prefix + ":" + name).encode())
            target = self.root / ref["path"]
            entries.append({**ref, "kind": kind, "fileIdentity": self._file_id(target),
                            "pathSha256": hashlib.sha256(os.fsencode(str(target))).hexdigest()})
        inventory = {"schemaVersion": "alk-r68b-raw-inventory.v1", "runId": "run", "taskId": "task",
                     "attemptId": attempt, "planDigest": self.authority["planDigest"],
                     "journalAuthorityKind": "SQLITE_ACCOUNTING_JOURNAL",
                     "journalIdentity": self.j.journal_identity, "eventLog": "journal.db",
                     "eventLogFileIdentity": self.authority["journalFileIdentity"],
                     "rootPathSha256": self.authority["rootPathSha256"],
                     "rootFileIdentity": self.authority["rootFileIdentity"],
                     "workflowStateDigest": digest({"localFixture": True}), "sources": entries}
        if operation_id is not None:
            inventory["operationId"] = operation_id
        ref = self._write(prefix + "/raw-inventory.json", canonical(inventory).encode())
        self.assertEqual(self.j.register_raw_inventory("run", ref, private_root=self.root,
                                                       authority_ref=self.authority_ref)["status"], "PENDING")
        self.sources[prefix] = [self.root / e["path"] for e in entries] + [self.root / ref["path"]]
        return ref

    def test_same_attempt_operations_retain_all_raw_obligations_and_original_summary(self):
        refs = [self._seal(), self._seal(operation_id="worker/one"), self._seal(operation_id="validator/two")]
        before = self.j.raw_obligations("run", self.clock_now.isoformat())
        self.assertEqual(len({row["obligationId"] for row in before}), 3)
        self.assertEqual({row["inventorySha256"] for row in before}, {ref["sha256"] for ref in refs})
        self.assertTrue(all(path.exists() for paths in self.sources.values() for path in paths))
        closed = self._close()
        summary = self.j.closed_run("run")["summary_digest"]
        self.assertEqual(self.j.collect_closed_run("run", closed.eligible_after).status, "COLLECTED")
        self.assertEqual(self._collect_raw(closed.eligible_after)["status"], "DONE")
        self.assertTrue(all(not path.exists() for paths in self.sources.values() for path in paths))
        self.assertEqual(self.j.closed_run("run")["summary_digest"], summary)
        self.assertEqual(self.j.snapshot("run").known_spent, 10)
        self.assertEqual(self.j.ingest_usage("run", self.original).status, "ALREADY_SETTLED")

    def _close(self):
        from agent_lifecycle.accounting.contracts import RunClosure

        now = datetime.now(UTC) + timedelta(seconds=1)
        closure = RunClosure("raw-closure", "run", "reportedTokens:fixture:v1", now.isoformat(),
                             (("run", self.j.snapshot("run").journal_revision),), self.proof, self.proof)
        result = self.j.close_run(closure, now.isoformat())
        self.assertEqual(result.status, "CLOSED")
        return result

    def _collect_raw(self, now):
        # Advance the injected runtime dependency explicitly for these local fixtures.
        # The public now_utc argument itself no longer authorizes deletion.
        self.clock_now = datetime.fromisoformat(now)
        return self.j.collect_raw_run("run", now, private_root=self.root, authority_ref=self.authority_ref)

    def _reopen(self):
        from agent_lifecycle.accounting.journal import Journal

        self.j.close()
        self.j = Journal(self.journal_path, self.proof, utc_clock=lambda: self.clock_now)

    def _ready_raw(self):
        self._seal()
        closed = self._close()
        self.j.collect_closed_run("run", closed.eligible_after)
        self.clock_now = datetime.fromisoformat(closed.eligible_after)
        return closed

    def _staging_path(self, index=0):
        key = self.j.raw_obligations("run", self.clock_now.isoformat())[0]["obligationId"]
        return self.sources["attempt-1"][index].parent / (".alk-delete-" + digest([key, index]))

    def test_raw_staging_collision_never_overwrites_unrelated_destination(self):
        closed = self._ready_raw()
        staging = self._staging_path()
        def collide(point):
            if point == "before_raw_stage":
                staging.write_bytes(b"unrelated destination")
                staging.chmod(0o600)
        self.j.fault_hook = collide
        with self.assertRaisesRegex(JournalUnavailable, "collision"):
            self._collect_raw(closed.eligible_after)
        self.assertEqual(staging.read_bytes(), b"unrelated destination")
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))
        self.assertEqual(self.j.raw_obligations("run", closed.eligible_after)[0]["status"], "PENDING")

    def test_raw_atomic_staging_crash_replays_only_exact_two_link_intermediate(self):
        closed = self._ready_raw()
        staging = self._staging_path()
        def fail(point):
            if point == "after_raw_stage":
                raise RuntimeError("crash after atomic link")
        self.j.fault_hook = fail
        with self.assertRaisesRegex(RuntimeError, "atomic link"):
            self._collect_raw(closed.eligible_after)
        source = self.sources["attempt-1"][0]
        self.assertEqual(source.stat().st_ino, staging.stat().st_ino)
        self.assertEqual(source.stat().st_nlink, 2)
        self._reopen()
        self.assertEqual(self._collect_raw(closed.eligible_after)["status"], "DONE")
        self.assertFalse(staging.exists())
        self.assertFalse(any(p.exists() for p in self.sources["attempt-1"]))

    def test_raw_recreation_after_unlink_refuses_done_and_keeps_obligation(self):
        closed = self._ready_raw()
        source = self.sources["attempt-1"][0]
        fired = []
        def recreate(point):
            if point == "after_raw_unlink" and not fired:
                source.write_bytes(b"recreated original")
                source.chmod(0o600)
                fired.append(point)
        self.j.fault_hook = recreate
        with self.assertRaisesRegex(JournalUnavailable, "recreated before DONE"):
            self._collect_raw(closed.eligible_after)
        self.assertEqual(source.read_bytes(), b"recreated original")
        self.assertEqual(self.j.raw_obligations("run", closed.eligible_after)[0]["status"], "PENDING")

    def test_raw_earlier_name_recreated_at_final_gate_refuses_done(self):
        closed = self._ready_raw()
        source = self.sources["attempt-1"][0]
        def recreate(point):
            if point == "before_raw_done":
                source.write_bytes(b"late original")
                source.chmod(0o600)
        self.j.fault_hook = recreate
        with self.assertRaisesRegex(JournalUnavailable, "recreated before DONE"):
            self._collect_raw(closed.eligible_after)
        self.assertEqual(source.read_bytes(), b"late original")
        self.assertEqual(self.j.raw_obligations("run", closed.eligible_after)[0]["status"], "PENDING")

    def test_raw_later_obligation_cannot_recreate_earlier_original_before_done(self):
        self._seal()
        self._seal("attempt-2")
        closed = self._close()
        self.j.collect_closed_run("run", closed.eligible_after)
        obligations = self.j.raw_obligations("run", closed.eligible_after)
        first_attempt = obligations[0]["attemptId"]
        first_source = self.sources[first_attempt][0]
        unlinks = []
        def recreate(point):
            if point == "after_raw_unlink":
                unlinks.append(point)
                if len(unlinks) == 5:
                    first_source.write_bytes(b"recreated by later obligation")
                    first_source.chmod(0o600)
        self.j.fault_hook = recreate
        with self.assertRaisesRegex(JournalUnavailable, "recreated before DONE"):
            self._collect_raw(closed.eligible_after)
        self.assertEqual(first_source.read_bytes(), b"recreated by later obligation")
        self.assertTrue(all(v["status"] == "PENDING" for v in self.j.raw_obligations("run", closed.eligible_after)))

    def test_raw_caller_future_timestamp_cannot_authorize_deletion(self):
        closed = self._ready_raw()
        self.clock_now = datetime.fromisoformat(closed.eligible_after) - timedelta(days=1)
        out = self.j.collect_raw_run("run", closed.eligible_after, private_root=self.root,
                                     authority_ref=self.authority_ref)
        self.assertEqual(out["status"], "NOT_DUE")
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))

    def test_raw_backward_clock_before_staged_unlink_refuses_and_restarts(self):
        closed = self._ready_raw()
        def backward(point):
            if point == "after_raw_original_unlink":
                self.clock_now -= timedelta(seconds=1)
        self.j.fault_hook = backward
        with self.assertRaisesRegex(JournalUnavailable, "clock unavailable or inconsistent"):
            self._collect_raw(closed.eligible_after)
        self.assertFalse(self.sources["attempt-1"][0].exists())
        self.assertTrue(self._staging_path().exists())
        self.assertEqual(self.j.raw_obligations("run", closed.eligible_after)[0]["status"], "PENDING")
        self._reopen()
        self.assertEqual(self._collect_raw(closed.eligible_after)["status"], "DONE")

    def test_raw_unavailable_runtime_clock_refuses_before_any_delete(self):
        closed = self._ready_raw()
        self.j._utc_clock = lambda: None
        with self.assertRaisesRegex(JournalUnavailable, "clock unavailable"):
            self.j.collect_raw_run("run", closed.eligible_after, private_root=self.root,
                                   authority_ref=self.authority_ref)
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))

    def test_raw_inconsistent_runtime_clock_before_staging_refuses(self):
        closed = self._ready_raw()
        def jump(point):
            if point == "before_raw_stage":
                self.clock_now += timedelta(seconds=10)
        self.j.fault_hook = jump
        with self.assertRaisesRegex(JournalUnavailable, "clock unavailable or inconsistent"):
            self._collect_raw(closed.eligible_after)
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))
        self.assertFalse(self._staging_path().exists())

    def test_raw_finite_original_utc_deadline_rechecked_before_staging(self):
        closed = self._ready_raw()
        deadline = (self.clock_now + timedelta(seconds=1)).isoformat()
        def expire(point):
            if point == "before_raw_stage":
                self.clock_now += timedelta(seconds=2)
        self.j.fault_hook = expire
        with self.assertRaisesRegex(JournalUnavailable, "original deadline exhausted"):
            self.j.collect_raw_run("run", closed.eligible_after, private_root=self.root,
                                   authority_ref=self.authority_ref, work_deadline_utc=deadline)
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))

    def test_raw_expired_inherited_monotonic_deadline_is_never_renewed(self):
        import time
        closed = self._ready_raw()
        original_deadline = time.monotonic() - 1
        self.j._maintenance_deadline = original_deadline
        with self.assertRaisesRegex(JournalUnavailable, "Write admission deadline expired|original deadline exhausted"):
            self._collect_raw(closed.eligible_after)
        self.assertEqual(self.j._maintenance_deadline, original_deadline)
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))

    def test_raw_well_formed_other_plan_lock_refused_before_registration_or_unlink(self):
        from agent_lifecycle.freeze import verify_plan_lock_envelope
        manifest = json.loads((self.root / self.manifest["path"]).read_bytes())
        lock = json.loads((self.root / self.lock["path"]).read_bytes())
        other = copy.deepcopy(manifest)
        other["planRevision"] += 1
        lock["planRevision"] = other["planRevision"]
        lock["manifestHash"] = digest(other)
        verify_plan_lock_envelope(other, lock)  # Internally consistent, still the wrong plan.
        self.authority["lockRef"] = self._write(self.lock["path"], canonical(lock).encode())
        self.authority_ref = self._write("maintenance-authority.json", canonical(self.authority).encode())
        with self.assertRaisesRegex(JournalUnavailable, "lock/manifest lineage mismatch"):
            self.j._raw_authority(self.root, self.authority_ref)
        with self.assertRaisesRegex(JournalUnavailable, "lock/manifest lineage mismatch"):
            self._seal()
        self.assertEqual(self.j.raw_obligations("run", self.clock_now.isoformat()), [])
        with self.assertRaisesRegex(JournalUnavailable, "lock/manifest lineage mismatch"):
            self._collect_raw(self.clock_now.isoformat())
        self.assertTrue((self.root / "attempt-1/input-request.json").exists())

    def test_raw_self_hashed_lock_inventory_requires_exact_manifest_membership(self):
        from agent_lifecycle.freeze import verify_plan_lock_envelope
        manifest = json.loads((self.root / self.manifest["path"]).read_bytes())
        lock = json.loads((self.root / self.lock["path"]).read_bytes())
        lock["entries"] = lock["entries"][:-1]
        lock["planFilesHash"] = digest({"schemaVersion": "agent-plan-file-inventory.v1", "entries": lock["entries"]})
        verify_plan_lock_envelope(manifest, lock)
        self.authority["lockRef"] = self._write(self.lock["path"], canonical(lock).encode())
        self.authority_ref = self._write("maintenance-authority.json", canonical(self.authority).encode())
        with self.assertRaisesRegex(JournalUnavailable, "inventory membership mismatch"):
            self.j._raw_authority(self.root, self.authority_ref)

    def test_retention_sql_collected_raw_pending_enumerates_every_attempt(self):
        first, second = self._seal(), self._seal("attempt-2")
        closed = self._close()
        with self.assertRaisesRegex(JournalUnavailable, "SQL collection must commit"):
            self._collect_raw(closed.eligible_after)
        self.assertTrue(all(p.exists() for paths in self.sources.values() for p in paths))
        summary = self.j.closed_run("run")["summary_digest"]
        self.assertEqual(self.j.collect_closed_run("run", closed.eligible_after).status, "COLLECTED")
        self.assertEqual(self.j._db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
        self._reopen()
        pending = self.j.raw_obligations("run", closed.eligible_after)
        self.assertEqual({v["inventorySha256"] for v in pending}, {first["sha256"], second["sha256"]})
        self.assertTrue(all(v["status"] == "PENDING" for v in pending))
        self.assertTrue(all(p.exists() for paths in self.sources.values() for p in paths))
        out = self.j.collect_raw_run("run", closed.eligible_after, private_root=self.root,
                                    authority_ref=self.authority_ref, candidate_limit=1)
        self.assertEqual(out["status"], "PENDING")
        self.assertEqual(sorted(v["status"] for v in out["obligations"]), ["DONE", "PENDING"])
        out = self._collect_raw(closed.eligible_after)
        self.assertEqual(out["status"], "DONE")
        self.assertTrue(all(not p.exists() for paths in self.sources.values() for p in paths))
        self.assertEqual(self.j.closed_run("run")["summary_digest"], summary)
        self.assertEqual(self.j.snapshot("run").known_spent, 10)
        self.assertEqual(self.j.ingest_usage("run", self.original).status, "ALREADY_SETTLED")

    def test_retention_partial_unlink_restart_is_idempotent_and_done_requires_all_files(self):
        self._seal()
        closed = self._close()
        self.j.collect_closed_run("run", closed.eligible_after)
        def fail(point):
            if point == "after_raw_unlink":
                raise RuntimeError("simulated crash after first unlink")
        self.j.fault_hook = fail
        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            self._collect_raw(closed.eligible_after)
        self.j.fault_hook = None
        self.assertEqual(sum(not p.exists() for p in self.sources["attempt-1"]), 1)
        self.assertEqual(self.j.raw_obligations("run", closed.eligible_after)[0]["status"], "PENDING")
        self._reopen()
        out = self._collect_raw(closed.eligible_after)
        self.assertEqual(out["status"], "DONE")
        statuses = [v["status"] for v in out["obligations"][0]["fileResults"]]
        self.assertEqual(statuses.count("alreadyAbsent"), 1)
        self.assertEqual(statuses.count("removed"), 3)
        self.assertFalse(any(p.exists() for p in self.sources["attempt-1"]))
        self.assertEqual(self._collect_raw(closed.eligible_after), out)

    def test_retention_due_check_refuses_open_not_due_and_financial_exception(self):
        from tests.accounting.test_normalization import observation

        self._seal()
        self.assertEqual(self._collect_raw(datetime.now(UTC).isoformat())["status"], "RUN_NOT_FULLY_CLOSED")
        self.assertIsNone(self.j.raw_obligations("run", datetime.now(UTC).isoformat())[0]["eligibleAfter"])
        closed = self._close()
        early = (datetime.fromisoformat(closed.eligible_after) - timedelta(microseconds=1)).isoformat()
        self.assertEqual(self._collect_raw(early)["status"], "NOT_DUE")
        self.j.collect_closed_run("run", closed.eligible_after)
        late = observation([self.op], [11], event="late-after-sql-collection")
        self.assertEqual(self.j.ingest_usage("run", late).status, "ACCOUNTING_RECONCILIATION_REQUIRED")
        self.assertEqual(self._collect_raw(closed.eligible_after)["status"], "ACCOUNTING_RECONCILIATION_REQUIRED")
        overdue = (datetime.fromisoformat(closed.eligible_after) + timedelta(hours=2, seconds=1)).isoformat()
        self.assertEqual(self.j.raw_obligations("run", overdue)[0]["status"], "OVERDUE")
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))
        self.assertEqual(self.j.snapshot("run").known_spent, 10)

    def test_retention_private_authority_rejects_modes_and_every_pinned_identity(self):
        self._seal()
        closed = self._close()
        self.j.collect_closed_run("run", closed.eligible_after)
        authority_path = self.root / self.authority_ref["path"]
        good = authority_path.read_bytes()
        for key in ("rootPathSha256", "rootFileIdentity", "journalIdentity", "journalFileIdentity",
                    "writerDigest", "storageVersion", "planDigest", "manifestRef", "lockRef", "allowedAction"):
            with self.subTest(key=key):
                altered = copy.deepcopy(self.authority)
                altered[key] = 999 if key == "storageVersion" else {} if isinstance(altered[key], dict) else "wrong"
                authority_path.write_bytes(canonical(altered).encode())
                altered_ref = {"path": self.authority_ref["path"], "sha256": hashlib.sha256(authority_path.read_bytes()).hexdigest(),
                               "bytes": authority_path.stat().st_size}
                with self.assertRaises(JournalUnavailable):
                    self.j._raw_authority(self.root, altered_ref)
                with self.assertRaises(JournalUnavailable):
                    self._collect_raw(closed.eligible_after)
                authority_path.write_bytes(good)
        for path, bad, restore in ((self.root, 0o755, 0o700), (authority_path, 0o644, 0o600),
                                  (self.journal_path, 0o644, 0o600),
                                  (self.sources["attempt-1"][0], 0o644, 0o600)):
            with self.subTest(path=str(path)):
                path.chmod(bad)
                with self.assertRaises(JournalUnavailable):
                    self._collect_raw(closed.eligible_after)
                path.chmod(restore)
        self.assertNotEqual(self.j.raw_obligations("run", closed.eligible_after)[0]["status"], "DONE")
        self.assertTrue(all(p.exists() for p in self.sources["attempt-1"]))

    def test_retention_late_exception_writer_fenced_through_recheck_and_unlink(self):
        self._seal()
        closed = self._close()
        self.j.collect_closed_run("run", closed.eligible_after)
        observed = []
        other = sqlite3.connect(str(self.journal_path), isolation_level=None, timeout=0)
        self.addCleanup(other.close)
        def fence(point):
            if point in ("before_raw_eligibility", "before_raw_unlink", "after_raw_unlink"):
                self.assertTrue(self.j._db.in_transaction)
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    other.execute("BEGIN IMMEDIATE")
                observed.append(point)
        self.j.fault_hook = fence
        self.assertEqual(self._collect_raw(closed.eligible_after)["status"], "DONE")
        self.j.fault_hook = None
        self.assertIn("before_raw_eligibility", observed)
        self.assertEqual(observed.count("before_raw_unlink"), 4)
        self.assertEqual(observed.count("after_raw_unlink"), 4)
        other.execute("BEGIN IMMEDIATE")
        other.execute("ROLLBACK")


if __name__ == "__main__":
    unittest.main()
