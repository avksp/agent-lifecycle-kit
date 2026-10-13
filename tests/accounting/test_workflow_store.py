"""Storage-version fencing before the workflow authority port is activated."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_lifecycle.accounting.closing_resource_policy import classify_current_claim_data, derive_policy_candidate_data
from agent_lifecycle.accounting.closing_resource_recovery import (
    _claim_in_transaction,
    _read_acknowledged_closing_grant_data,
    _read_acknowledged_closing_operation_data,
    _read_existing_closing_operation_data,
    _reserve_in_transaction,
    _resolve_pinned_native_operation_data,
    read_persisted_closing_balances,
    reconstruct_closing_balances,
)
from agent_lifecycle.accounting.contracts import (
    BudgetScope,
    EvidenceRef,
    OpeningBalance,
    RunClosure,
    canonical,
    digest,
)
from agent_lifecycle.accounting.journal import Journal, JournalUnavailable
from agent_lifecycle.accounting.workflow_authority_store import (
    AUTHORITY_TABLES,
    _financial_snapshot_digest,
    _load_run_output_anchor_data,
    _storage_schema_digest,
    install_successor_snapshot,
)
from agent_lifecycle.accounting.workflow_state_store import WORKFLOW_TABLES, WorkflowStore, create_workflow_schema
from agent_lifecycle.accounting.workflow_store import BASE_STATEMENTS
from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.workflow_authority_schemas import (
    AUTHORITY_DECISION_V1,
    AUTHORITY_INPUT_BUNDLE_V1,
    AUTHORITY_SNAPSHOT_V1,
    validate_authority_decision_shape,
)
from tests.accounting.test_workflow_authority_store import DOMAIN, ROOT_SEED
from tests.contracts.test_workflow_authority import _grant, _issuer, _pin, _signed
from tests.workflow.test_closing_policy import _context

from .test_closing_resources import ClosingResourceCandidateTests
from .test_journal import open_scope, operation, receipt
from .test_normalization import observation
from .test_opening_balances import import_data

WRITER = EvidenceRef("test-writer", "a" * 64)


class WorkflowSchemaTests(unittest.TestCase):
    @staticmethod
    def _binding(journal: Journal) -> dict:
        ref = {"path": "pin.json", "sha256": "c" * 64, "bytes": 10}
        return {
            "schemaVersion": "agent-workflow-journal-binding.v1",
            "bindingId": "binding", "runId": "run", "packageId": "package", "budgetScopeId": "scope",
            "canonicalStatePath": "state.json", "journalPath": str(journal._path),
            "journalIdentity": journal.journal_identity, "storageProtocolVersion": "5",
            "workflowProtocolVersion": "1", "planDigest": "a" * 64, "sourceRevision": "source",
            "adoptionEpoch": "epoch-1", "authorityMode": "JOURNAL_REQUIRED",
            "workflowAuthorityPinRef": ref, "resourceInventoryRef": ref, "deadlineInventoryRef": ref,
        }

    @staticmethod
    def _state() -> dict:
        return {
            "schemaVersion": "agent-workflow-state.v4", "runId": "run", "packageId": "package",
            "planRevision": 1, "planDigest": "a" * 64, "sourceRevision": "source", "stateRevision": 1,
            "phase": "RUNNING", "eventLog": "events.jsonl", "operationLedger": {},
            "tasks": [{"id": "WS-01", "status": "READY", "attempt": 0, "dependsOn": [],
                       "attemptHistory": [], "required": True}],
        }

    def _v4(self, path: Path) -> None:
        with sqlite3.connect(path, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            for statement in BASE_STATEMENTS:
                db.execute(statement)
            db.execute("INSERT INTO schema_metadata VALUES(1,4)")
            for table in ("events", "identities"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable journal record'); END"
                    )
            dummy = object.__new__(Journal)
            dummy._owner = (os.getpid(), threading.get_ident())
            dummy._connection = db
            dummy._create_v2_schema()
            Journal._create_writer_guard(db, 4)
            Journal._create_v4_schema(db)
            db.execute("COMMIT")
            Journal._validate_schema(db, 4)

    def test_fresh_v5_has_exact_closed_workflow_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "new.db", WRITER) as journal:
            expected = set(WORKFLOW_TABLES) | set(AUTHORITY_TABLES)
            self.assertEqual(len(expected), 18)
            found = {
                row[0]
                for row in journal._db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if row[0] in expected
            }
            self.assertEqual(found, expected)

    def test_v6_workflow_guard_template_fences_v5_writer_and_metadata(self) -> None:
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE schema_metadata(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)")
            db.execute("INSERT INTO schema_metadata VALUES(1,6)")
            db.create_function("alk_storage_writer_version", 0, lambda: 6)
            create_workflow_schema(db, writer_version=6)
            self.assertTrue({
                "workflow_run_output_anchors", "workflow_proof_body_stage", "workflow_storage_migrations"
            } <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            db.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", ("run-1", "a" * 64, "{}"))
            db.create_function("alk_storage_writer_version", 0, lambda: 5)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", ("run-2", "b" * 64, "{}"))
            db.create_function("alk_storage_writer_version", 0, lambda: 6)
            db.execute("UPDATE schema_metadata SET version=5 WHERE singleton=1")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", ("run-3", "c" * 64, "{}"))
            receipt = (1, "init-v6", None, 6, None, "d" * 64, "e" * 64, "f" * 64)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO workflow_storage_migrations VALUES(?,?,?,?,?,?,?,?)", receipt)
            db.execute("UPDATE schema_metadata SET version=6 WHERE singleton=1")
            db.execute("INSERT INTO workflow_storage_migrations VALUES(?,?,?,?,?,?,?,?)", receipt)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE workflow_storage_migrations SET new_schema_digest=?", ("0" * 64,))
            with self.assertRaises(ValueError):
                create_workflow_schema(db, writer_version=7)

    def test_v6_anchor_sql_row_matches_each_canonical_anchor_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v6.db"
            with Journal(path, WRITER, storage_version=6) as journal:
                binding = self._binding(journal)
                binding["storageProtocolVersion"] = "6"
                journal._db.execute(
                    "INSERT INTO workflow_bindings VALUES(?,?,?)",
                    ("run", canonical_digest(binding), canonical(binding)),
                )
                journal._db.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", ("wrong-run", "a" * 64, "{}"))
                with self.assertRaises(JournalUnavailable):
                    _load_run_output_anchor_data(journal._db, binding, canonical_digest(binding))
                anchor = {
                    "schemaVersion": "agent-run-output-anchor.v1",
                    "runId": "run", "bindingDigest": canonical_digest(binding),
                    "adoptedStateDigest": "b" * 64, "journalIdentity": journal.journal_identity,
                    "storageProtocolVersion": "6", "artifactAuthorityRootPath": str(Path(directory) / "root"),
                    "artifactAuthorityRootIdentity": {"platform": "POSIX", "volumeId": "volume", "fileId": "file"},
                    "canonicalStatePath": "state.json", "packageRoot": "package",
                    "resolvedPackageRootRelativePath": "package", "eventLog": "events.jsonl",
                    "runOutputRootRelativePath": ".alk-closing/run",
                }
                raw = canonical(anchor).encode("utf-8")
                row = [
                    "run", anchor["bindingDigest"], anchor["adoptedStateDigest"], anchor["journalIdentity"],
                    anchor["artifactAuthorityRootPath"], "POSIX", "volume", "file", "package",
                    "events.jsonl", ".alk-closing/run", raw, hashlib.sha256(raw).hexdigest(), 6,
                ]
                for index in range(11):
                    with self.subTest(column=index):
                        changed = row.copy()
                        changed[index] = "wrong-run" if index == 0 else "wrong"
                        with self.assertRaises(sqlite3.IntegrityError):
                            journal._db.execute(
                                "INSERT INTO workflow_run_output_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", changed
                            )
                        self.assertEqual(journal._db.execute(
                            "SELECT COUNT(*) FROM workflow_run_output_anchors"
                        ).fetchone()[0], 0)
                changed = row.copy()
                changed[12] = "0" * 64
                with self.assertRaises(sqlite3.IntegrityError):
                    journal._db.execute(
                        "INSERT INTO workflow_run_output_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", changed
                    )
                journal._db.execute(
                    "INSERT INTO workflow_run_output_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row
                )
                self.assertEqual(_load_run_output_anchor_data(journal._db, binding, canonical_digest(binding)), anchor)
                with sqlite3.connect(":memory:") as detached:
                    detached.row_factory = sqlite3.Row
                    detached.execute("CREATE TABLE workflow_bindings(run_id,binding_digest,payload)")
                    detached.execute(
                        "CREATE TABLE workflow_run_output_anchors(" + ",".join((
                            "run_id", "binding_digest", "adopted_state_digest", "journal_identity",
                            "artifact_root_path", "root_platform", "root_volume_id", "root_file_id",
                            "package_root", "event_log", "output_root_relative_path",
                            "canonical_anchor_bytes", "anchor_digest", "storage_version",
                        )) + ")"
                    )
                    detached.execute("INSERT INTO workflow_bindings VALUES(?,?,?)",
                                     ("run", canonical_digest(binding), canonical(binding)))
                    detached.execute("INSERT INTO workflow_run_output_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
                    self.assertEqual(
                        _load_run_output_anchor_data(detached, binding, canonical_digest(binding)), anchor,
                    )
                    detached.execute("UPDATE workflow_bindings SET payload='{}' WHERE run_id='run'")
                    with self.assertRaises(JournalUnavailable):
                        _load_run_output_anchor_data(detached, binding, canonical_digest(binding))
                native = replace(operation("run", name="native", upper=7), budget_scope_id="scope")
                native_raw = canonical(asdict(native)).encode("utf-8")
                output = Path(anchor["artifactAuthorityRootPath"]) / anchor["runOutputRootRelativePath"]
                output.mkdir(parents=True)
                (output / "operation.json").write_bytes(native_raw)
                sidecar = {
                    "schemaVersion": "agent-closing-operation-binding.v1", "bindingId": "binding",
                    "runId": "run", "budgetScopeId": "scope", "closingWindowId": "window",
                    "policyEffectDigest": "f" * 64, "operationId": "native",
                    "nativeOperationRef": {"path": ".alk-closing/run/operation.json",
                                           "sha256": hashlib.sha256(native_raw).hexdigest(),
                                           "bytes": len(native_raw)},
                    "nativeOperationDigest": native.binding_digest, "action": "accounting-closeout",
                    "owner": {"scopeKind": "TASK", "taskId": "task"},
                    "unit": {"metric": "reportedTokens", "unitDefinitionId": native.unit_definition_id,
                             "definitionDigest": "d" * 64, "sourceQualificationDigest": "e" * 64},
                    "upperBound": 7, "expectedJournalRevision": 0,
                    "expectedWorkflowRevision": 0, "expectedAuthorityEpoch": 0,
                    "expectedGuardStateDigest": "f" * 64,
                }
                with self.assertRaises(JournalUnavailable):
                    _resolve_pinned_native_operation_data(journal, binding, canonical_digest(binding), sidecar)
                with journal._transaction():
                    joined = _resolve_pinned_native_operation_data(
                        journal, binding, canonical_digest(binding), sidecar,
                    )
                    self.assertEqual(joined["anchor"], anchor)
                    self.assertEqual(joined["operation"], native)
                    self.assertFalse(joined["rootQualificationVerified"])
                    self.assertFalse(joined["financialAdmission"])
                    with self.assertRaises(LifecycleError):
                        _resolve_pinned_native_operation_data(
                            journal, binding, canonical_digest(binding), {**sidecar, "runId": "other-run"},
                        )
                    with self.assertRaises(LifecycleError):
                        _resolve_pinned_native_operation_data(
                            journal, binding, canonical_digest(binding),
                            {**sidecar, "nativeOperationRef": {**sidecar["nativeOperationRef"],
                                                                 "path": "operation.json"}},
                        )
                    with self.assertRaises(LifecycleError):
                        _resolve_pinned_native_operation_data(
                            journal, binding, canonical_digest(binding),
                            {**sidecar, "nativeOperationRef": {**sidecar["nativeOperationRef"],
                                                                 "sha256": "0" * 64}},
                        )
                changed_binding = {**binding, "canonicalStatePath": "other.json"}
                with self.assertRaises(JournalUnavailable):
                    _load_run_output_anchor_data(journal._db, changed_binding, canonical_digest(changed_binding))
            with Journal(path, WRITER, storage_version=6) as reopened:
                self.assertEqual(reopened._db.execute(
                    "SELECT canonical_anchor_bytes FROM workflow_run_output_anchors WHERE run_id='run'"
                ).fetchone()[0], raw)
                self.assertEqual(_load_run_output_anchor_data(reopened._db, binding, canonical_digest(binding)), anchor)

    def test_synthetic_existing_window_operation_join_is_data_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(
            Path(directory) / "join.db", WRITER, storage_version=6,
        ) as journal:
            binding = self._binding(journal)
            binding["storageProtocolVersion"] = "6"
            fixture_issuer = _issuer()
            issuer = {
                **fixture_issuer,
                "validFrom": "2020-01-01T00:00:00.000000Z",
                "expiresAt": "2100-01-01T00:00:00.000000Z",
                "scope": {
                    **fixture_issuer["scope"], "budgetScopeId": "scope",
                    "journalIdentity": journal.journal_identity,
                    "originalPlanDigest": "a" * 64, "effectivePlanDigest": "a" * 64,
                },
            }
            initial_authority = _signed({
                "schemaVersion": AUTHORITY_SNAPSHOT_V1,
                "authorityDomain": "authority:run", "rootId": "root",
                "rootGeneration": "generation:1", "bindingId": "binding",
                "journalIdentity": journal.journal_identity, "epoch": 0,
                "previousSnapshotDigest": None,
                "validFrom": "2020-01-01T00:00:00.000000Z",
                "expiresAt": "2100-01-01T00:00:00.000000Z",
                "activeIssuers": [issuer], "revokedIssuers": [], "revokedGrants": [],
            }, ROOT_SEED, DOMAIN)
            pin = {
                **_pin(), "budgetScopeId": "scope",
                "journalIdentity": journal.journal_identity,
                "expectedInitialSnapshotDigest": canonical_digest(initial_authority),
            }
            pin_record = {
                "pin": pin, "pinRef": binding["workflowAuthorityPinRef"],
                "bindingDigest": canonical_digest(binding),
                "qualificationDigest": pin["qualificationRef"]["sha256"],
            }
            signed_grant = _signed({
                **_grant(), "scope": issuer["scope"],
                "validFrom": "2020-01-01T00:00:00.000000Z",
                "expiresAt": "2100-01-01T00:00:00.000000Z",
                "issuedUnderEpoch": 0,
                "issuedUnderSnapshotDigest": canonical_digest(initial_authority),
                "expectedWorkflowRevision": 1,
            }, bytes(range(1, 33)), b"agent-lifecycle-workflow-closing-grant-v1\x00")
            grant_raw = canonical(signed_grant).encode("utf-8")
            grant_ref = {"path": "fixture-grant.json",
                         "sha256": hashlib.sha256(grant_raw).hexdigest(), "bytes": len(grant_raw)}
            unused_ref = {"path": "unused.json", "sha256": "a" * 64, "bytes": 1}
            authority_input = {
                "schemaVersion": AUTHORITY_INPUT_BUNDLE_V1,
                "bindingId": "binding", "pinDigest": canonical_digest(pin),
                "grantRef": grant_ref,
                "issuanceSnapshotDigest": canonical_digest(initial_authority),
                "expectedCurrentEpoch": 0,
                "windowRequestRef": unused_ref, "resourceApprovalRef": unused_ref,
                "allowedWritesRef": unused_ref, "deadlineInputRef": unused_ref,
            }
            observed = {
                "schemaVersion": "agent-workflow-clock-observation.v1",
                "journalIdentity": journal.journal_identity,
                "processIdentity": "fixture-process",
                "observedAt": "2026-09-23T01:30:00.000000Z",
                "monotonicNanos": 1, "monotonicOriginId": "fixture-origin",
                "previousAcceptedUtc": "2020-01-01T00:00:00.000000Z",
                "clockQualificationDigest": "a" * 64,
            }
            inventory, proposal, before, policy_anchor = ClosingResourceCandidateTests._inputs()
            inventory.update(budgetScopeId="scope", journalIdentity=journal.journal_identity, taskIds=[])
            proposal.update(budgetScopeId="scope", journalIdentity=journal.journal_identity,
                            inventoryDigest=canonical_digest(inventory), expectedJournalRevision=1,
                            limits=proposal["limits"][:1],
                            protectionAllocations=proposal["protectionAllocations"][:1])
            policy_anchor["journalRevision"] = 1
            for field in ("spent", "reservations", "protected", "violationsByOwner"):
                policy_anchor[field] = {"": policy_anchor[field][""]}
            self.assertEqual(journal.open_scope(
                BudgetScope("scope", "run", "tokens"), before,
                OpeningBalance("opening", "source", "tokens", {}, 120, (), WRITER, WRITER),
            ), "OPENED")
            derived = derive_policy_candidate_data(inventory, proposal, before, policy_anchor)
            candidate = derived["candidate"]
            effect = {
                "schemaVersion": "agent-closing-resource-effect.v1",
                "candidateDigest": digest(candidate), "proposalDigest": digest(proposal),
                "runId": "run", "budgetScopeId": "scope", "closingWindowId": "window",
                "activationOperationId": "synthetic-activation",
                "authorityDecisionDigest": "a" * 64, "grantDigest": "b" * 64,
                "beforeJournalRevision": 1, "afterJournalRevision": 2,
                "beforePolicy": candidate["beforePolicy"], "afterPolicy": candidate["afterPolicy"],
            }
            effect_digest = digest(effect)
            record = {"effect": effect, "candidate": candidate, "proposal": proposal,
                      "nativeBeforePolicy": asdict(before),
                      "nativeAfterPolicy": derived["nativeAfterPolicy"]}
            with journal._transaction():
                financial_state, revision = journal._load("scope")
                journal._record("scope", financial_state, revision, "CLOSING_POLICY_APPLIED", record)
            native = replace(
                operation("scope", name="native", task=None, upper=7, closeout=True),
                run_id="run", policy_revision=2, unit_definition_id="tokens",
            )
            native_raw = canonical(asdict(native)).encode("utf-8")
            root = Path(directory) / "root"
            output = root / ".alk-closing/run"
            output.mkdir(parents=True)
            (output / "operation.json").write_bytes(native_raw)
            sidecar = {
                "schemaVersion": "agent-closing-operation-binding.v1",
                "bindingId": "binding", "runId": "run", "budgetScopeId": "scope",
                "closingWindowId": "window", "policyEffectDigest": effect_digest,
                "operationId": "native",
                "nativeOperationRef": {"path": ".alk-closing/run/operation.json",
                                       "sha256": hashlib.sha256(native_raw).hexdigest(),
                                       "bytes": len(native_raw)},
                "nativeOperationDigest": native.binding_digest,
                "action": "accounting-closeout", "owner": {"scopeKind": "RUN", "taskId": None},
                "unit": proposal["unit"], "upperBound": 7,
                "expectedJournalRevision": 2, "expectedWorkflowRevision": 1,
                "expectedAuthorityEpoch": 0, "expectedGuardStateDigest": "f" * 64,
            }
            bucket = {"schemaVersion": "agent-closing-protection-bucket.v1",
                      "budgetScopeId": "scope", "owner": {"scopeKind": "RUN", "taskId": None},
                      "originWindowId": "window", "unspent": 3}
            state = self._state()
            context = _context()
            context.update(planDigest=state["planDigest"], journalIdentity=journal.journal_identity,
                           resourcePolicyEffectDigest=effect_digest,
                           windowGrantDigest=canonical_digest(signed_grant))
            context["contextDigest"] = canonical_digest({
                key: value for key, value in context.items() if key != "contextDigest"
            })
            state["closingWindow"] = context
            anchor = {
                "schemaVersion": "agent-run-output-anchor.v1", "runId": "run",
                "bindingDigest": canonical_digest(binding), "adoptedStateDigest": digest(state),
                "journalIdentity": journal.journal_identity, "storageProtocolVersion": "6",
                "artifactAuthorityRootPath": str(root),
                "artifactAuthorityRootIdentity": {"platform": "POSIX", "volumeId": "synthetic",
                                                   "fileId": "synthetic"},
                "canonicalStatePath": binding["canonicalStatePath"], "packageRoot": "package",
                "resolvedPackageRootRelativePath": "package", "eventLog": "events.jsonl",
                "runOutputRootRelativePath": ".alk-closing/run",
            }
            anchor_raw = canonical(anchor).encode("utf-8")
            before_reserve = journal.snapshot("scope")
            with self.assertRaisesRegex(RuntimeError, "fixture rollback"), journal._transaction():
                self.assertEqual(_reserve_in_transaction(journal, native, expected_revision=2), "RESERVED")
                trial_state, trial_revision = journal._load("scope")
                trial_balances = reconstruct_closing_balances(
                    trial_state, trial_revision, proposal, [sidecar], [bucket], effect_digest,
                )
                journal._db.execute("INSERT INTO closing_policy_effects VALUES(?,?,?,?)", (
                    "run", "window", effect_digest, canonical(record),
                ))
                journal._db.execute("INSERT INTO closing_operation_bindings VALUES(?,?,?,?)", (
                    "scope", "native", digest(sidecar), canonical(sidecar),
                ))
                journal._db.execute("INSERT INTO closing_protection_buckets VALUES(?,?,?,?,?)", (
                    "scope", "", "window", trial_revision, canonical(bucket),
                ))
                for balance in trial_balances:
                    journal._db.execute("INSERT INTO closing_resource_balances VALUES(?,?,?,?,?)", (
                        "scope", "window", balance["scope"]["taskId"] or "", trial_revision,
                        canonical(balance),
                    ))
                raise RuntimeError("fixture rollback")
            self.assertEqual(journal.snapshot("scope"), before_reserve)
            for table in (
                "closing_policy_effects", "closing_operation_bindings",
                "closing_protection_buckets", "closing_resource_balances",
            ):
                self.assertEqual(journal._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            with journal._transaction():
                db = journal._db
                self.assertEqual(_reserve_in_transaction(journal, native, expected_revision=2), "RESERVED")
                financial_state, revision = journal._load("scope")
                balances = reconstruct_closing_balances(
                    financial_state, revision, proposal, [sidecar], [bucket], effect_digest,
                )
                db.execute("INSERT INTO workflow_bindings VALUES(?,?,?)",
                           ("run", canonical_digest(binding), canonical(binding)))
                db.execute("INSERT INTO workflow_authority_roots VALUES(?,?,?)", (
                    "binding", canonical_digest(pin), canonical(pin_record),
                ))
                db.execute("INSERT INTO workflow_authority_snapshots VALUES(?,?,?,?,?,?)", (
                    "binding", 0, canonical_digest(initial_authority), None,
                    "bootstrap", canonical(initial_authority),
                ))
                db.execute("INSERT INTO workflow_authority_current VALUES(?,?,?,?)", (
                    "binding", 0, canonical_digest(initial_authority),
                    "2020-01-01T00:00:00.000000Z",
                ))
                db.execute("INSERT INTO workflow_clock_high_water VALUES(?,?)", (
                    journal.journal_identity, "2020-01-01T00:00:00.000000Z",
                ))
                db.execute("INSERT INTO workflow_run_output_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    "run", anchor["bindingDigest"], anchor["adoptedStateDigest"],
                    anchor["journalIdentity"], str(root), "POSIX", "synthetic", "synthetic",
                    "package", "events.jsonl", ".alk-closing/run", anchor_raw,
                    hashlib.sha256(anchor_raw).hexdigest(), 6,
                ))
                db.execute("INSERT INTO workflow_states VALUES(?,?,?,?,?)",
                           ("run", 1, digest(state), canonical(state), 1))
                db.execute("INSERT INTO workflow_projection_outbox VALUES(?,?,?,?,?,?,?)",
                           ("run", 1, digest(state), "e" * 64, canonical({}), "PENDING", None))
                db.execute("INSERT INTO closing_policy_effects VALUES(?,?,?,?)",
                           ("run", "window", effect_digest, canonical(record)))
                db.execute("INSERT INTO closing_operation_bindings VALUES(?,?,?,?)",
                           ("scope", "native", digest(sidecar), canonical(sidecar)))
                db.execute("INSERT INTO closing_protection_buckets VALUES(?,?,?,?,?)",
                           ("scope", "", "window", revision, canonical(bucket)))
                for balance in balances:
                    db.execute("INSERT INTO closing_resource_balances VALUES(?,?,?,?,?)", (
                        "scope", "window", balance["scope"]["taskId"] or "", revision,
                        canonical(balance),
                    ))
            store = WorkflowStore(journal, binding, canonical_digest(binding))
            with self.assertRaises(JournalUnavailable):
                _read_existing_closing_operation_data(store, sidecar)
            with self.assertRaisesRegex(JournalUnavailable, "admitted transaction"):
                _read_acknowledged_closing_operation_data(store, sidecar)
            with journal._transaction():
                selected = _read_existing_closing_operation_data(store, sidecar)
                self.assertEqual(selected["status"], "CURRENT_DATA")
                self.assertEqual(selected["operation"], native)
                self.assertEqual(selected["journalRevision"], 3)
                self.assertFalse(selected["rootQualificationVerified"])
                self.assertTrue(selected["accountingReplayVerified"])
                self.assertFalse(selected["financialAdmission"])
                before_ack_gate = db.total_changes
                with self.assertRaisesRegex(JournalUnavailable, "not acknowledged"):
                    _read_acknowledged_closing_operation_data(store, sidecar)
                self.assertEqual(db.total_changes, before_ack_gate)
                with self.assertRaisesRegex(JournalUnavailable, "not acknowledged"):
                    store._read_acknowledged_closing_authority_data_in_transaction(
                        sidecar, authority_input,
                    )
                db.execute(
                    "UPDATE workflow_projection_outbox SET status='ACK',ack_digest=? "
                    "WHERE run_id='run' AND generation=1", ("a" * 64,),
                )
                after_ack_update = db.total_changes
                acknowledged = _read_acknowledged_closing_operation_data(store, sidecar)
                self.assertEqual(acknowledged["operation"], native)
                self.assertTrue(acknowledged["sqlProjectionAckObserved"])
                self.assertTrue(acknowledged["workflowRevisionMatched"])
                self.assertFalse(acknowledged["financialAdmission"])
                self.assertFalse(acknowledged["nativePermissionGranted"])
                self.assertEqual(db.total_changes, after_ack_update)
                authority_join = store._read_acknowledged_closing_authority_data_in_transaction(
                    sidecar, authority_input,
                )
                self.assertEqual(authority_join["authorityEpoch"], 0)
                self.assertTrue(authority_join["authorityHistoryCryptoVerified"])
                self.assertTrue(authority_join["authorityData"]["historyCryptoVerified"])
                for flag in ("rootQualificationVerified", "clockQualified", "grantQualified",
                             "financialAdmission", "nativePermissionGranted"):
                    self.assertFalse(authority_join[flag])
                self.assertEqual(db.total_changes, after_ack_update)
                grant_join = _read_acknowledged_closing_grant_data(
                    store, sidecar, authority_input, grant_raw, observed,
                )
                self.assertEqual(grant_join["grantDigest"], canonical_digest(signed_grant))
                self.assertTrue(grant_join["grantData"]["grantSignatureVerifiedAtSuppliedTime"])
                self.assertTrue(grant_join["currentWindowDataMatched"])
                self.assertTrue(grant_join["suppliedTimeInsideWindow"])
                self.assertEqual(grant_join["claimHeadroomData"]["disposition"], "DATA_CANDIDATE")
                self.assertTrue(grant_join["claimHeadroomData"]["operationReservationDataMatched"])
                self.assertTrue(grant_join["claimHeadroomData"]["proposalBalanceDataMatched"])
                self.assertTrue(grant_join["claimHeadroomData"]["headroom"]["upperBoundCountedOnce"])
                self.assertFalse(grant_join["claimHeadroomData"]["financialAdmission"])
                self.assertFalse(grant_join["claimHeadroomData"]["nativePermissionGranted"])
                claimed_data = {**grant_join, "storedOperation": {
                    **grant_join["storedOperation"], "claim_id": "already-claimed",
                }}
                self.assertEqual(
                    classify_current_claim_data(claimed_data, sidecar)["disposition"], "REFUSED",
                )
                with self.assertRaises(LifecycleError):
                    classify_current_claim_data(
                        {**grant_join, "proposal": {**grant_join["proposal"], "bindingId": "wrong"}},
                        sidecar,
                    )
                for flag in ("rootQualificationVerified", "clockQualified", "grantQualified",
                             "financialAdmission", "nativePermissionGranted"):
                    self.assertFalse(grant_join[flag])
                self.assertEqual(db.total_changes, after_ack_update)
                with self.assertRaisesRegex(JournalUnavailable, "raw bytes differ"):
                    _read_acknowledged_closing_grant_data(
                        store, sidecar, authority_input, grant_raw + b" ", observed,
                    )
                other_grant = _signed(
                    {**signed_grant, "nonce": "b" * 64}, bytes(range(1, 33)),
                    b"agent-lifecycle-workflow-closing-grant-v1\x00",
                )
                other_raw = canonical(other_grant).encode("utf-8")
                other_input = {**authority_input, "grantRef": {
                    "path": "other-grant.json", "sha256": hashlib.sha256(other_raw).hexdigest(),
                    "bytes": len(other_raw),
                }}
                with self.assertRaisesRegex(JournalUnavailable, "grant/context data join differs"):
                    _read_acknowledged_closing_grant_data(
                        store, sidecar, other_input, other_raw, observed,
                    )
                with self.assertRaisesRegex(JournalUnavailable, "grant/context data join differs"):
                    _read_acknowledged_closing_grant_data(
                        store, sidecar, authority_input, grant_raw,
                        {**observed, "observedAt": "2026-09-23T02:00:00.000000Z"},
                    )
                self.assertEqual(db.total_changes, after_ack_update)
                db.execute("SAVEPOINT stale_workflow")
                stale_state = {**state, "stateRevision": 2}
                stale_digest = digest(stale_state)
                db.execute(
                    "UPDATE workflow_states SET revision=2,state_digest=?,state_json=? "
                    "WHERE run_id='run'", (stale_digest, canonical(stale_state)),
                )
                db.execute(
                    "UPDATE workflow_projection_outbox SET state_digest=? "
                    "WHERE run_id='run' AND generation=1", (stale_digest,),
                )
                before_stale_refusal = db.total_changes
                with self.assertRaisesRegex(JournalUnavailable, "workflow revision is stale"):
                    _read_acknowledged_closing_operation_data(store, sidecar)
                self.assertEqual(db.total_changes, before_stale_refusal)
                db.execute("ROLLBACK TO stale_workflow")
                db.execute("RELEASE stale_workflow")
                successor = _signed({
                    **initial_authority, "epoch": 1,
                    "previousSnapshotDigest": canonical_digest(initial_authority),
                    "revokedGrants": [{
                        "issuerId": "issuer", "issuerGeneration": "generation:1", "nonce": "a" * 64,
                    }],
                }, ROOT_SEED, DOMAIN)
                installed = install_successor_snapshot(
                    db, binding, canonical_digest(binding), successor, "rotation", 0,
                )
                self.assertEqual(installed["status"], "INSTALLED")
                after_rotation = db.total_changes
                with self.assertRaisesRegex(JournalUnavailable, "current authority epoch differs"):
                    store._read_acknowledged_closing_authority_data_in_transaction(
                        sidecar, authority_input,
                    )
                self.assertEqual(db.total_changes, after_rotation)
                with self.assertRaisesRegex(JournalUnavailable, "authority epoch is stale"):
                    store._read_acknowledged_closing_authority_data_in_transaction(
                        sidecar, {**authority_input, "expectedCurrentEpoch": 1},
                    )
                self.assertEqual(db.total_changes, after_rotation)
                with self.assertRaises(JournalUnavailable):
                    _read_existing_closing_operation_data(
                        store, {**sidecar, "policyEffectDigest": "0" * 64},
                    )
                db.execute("UPDATE closing_resource_balances SET generation=2 WHERE budget_scope_id='scope'")
                with self.assertRaises(JournalUnavailable):
                    _read_existing_closing_operation_data(store, sidecar)
            before_legacy = journal.snapshot("scope")
            changes = journal._db.total_changes
            self.assertEqual(store.claim_with_workflow_authority({})["status"], "DENY")
            bypass = replace(
                operation("scope", name="legacy-bypass", task=None, upper=1, closeout=True),
                run_id="run", policy_revision=2, unit_definition_id="tokens",
            )
            self.assertEqual(journal.reserve(bypass, expected_revision=3), "DENY")
            self.assertEqual(journal.claim("scope", "native", native.binding_digest, "claim:legacy-bypass"), "DENY")
            self.assertEqual(journal.snapshot("scope"), before_legacy)
            self.assertEqual(journal._db.total_changes, changes)
            ordinary = replace(
                operation("scope", name="ordinary", task=None, upper=1),
                run_id="run", policy_revision=2, unit_definition_id="tokens",
            )
            self.assertEqual(journal.reserve(ordinary, expected_revision=3), "DENY")
            self.assertEqual(journal.snapshot("scope"), before_legacy)
            self.assertEqual(journal._db.total_changes, changes)
            with journal._transaction():
                self.assertEqual(_reserve_in_transaction(journal, ordinary, expected_revision=3), "RESERVED")
            before_claim = journal.snapshot("scope")
            changes = journal._db.total_changes
            self.assertEqual(journal.claim("scope", "ordinary", ordinary.binding_digest, "claim:ordinary"), "DENY")
            self.assertEqual(journal.snapshot("scope"), before_claim)
            self.assertEqual(journal._db.total_changes, changes)
            # Storage atomicity only: this shaped decision is not signed or operator-qualified.
            claim_id = "claim:native"
            claim_decision = validate_authority_decision_shape({
                "schemaVersion": AUTHORITY_DECISION_V1,
                "decisionId": "synthetic-claim", "bindingId": binding["bindingId"],
                "journalIdentity": journal.journal_identity,
                "authorityDomain": "synthetic:run", "rootFingerprint": "ed25519:" + "0" * 64,
                "issuerId": "synthetic-issuer", "issuerGeneration": "synthetic-generation",
                "nonce": "a" * 64, "grantDigest": "b" * 64,
                "currentSnapshotDigest": "c" * 64, "authorityEpoch": 0,
                "operationId": native.operation_id, "requestDigest": "d" * 64,
                "expectedWorkflowRevision": 1,
                "authorizedAt": "2026-09-23T01:00:00.000000Z",
                "expiresAt": "2026-09-23T02:00:00.000000Z",
                "permission": "closing.activate", "windowIntentDigest": "e" * 64,
                "resourceApprovalDigest": "f" * 64, "allowedWritesDigest": "0" * 64,
                "decisionKind": "CLAIM", "claimId": claim_id, "action": "finalize",
                "clockObservationDigest": "1" * 64,
            })
            decision_digest = digest(claim_decision)
            before_claim = journal.snapshot("scope")
            with self.assertRaisesRegex(RuntimeError, "claim fixture rollback"), journal._transaction():
                self.assertEqual(_claim_in_transaction(
                    journal, "scope", native.operation_id, native.binding_digest, claim_id,
                ), "CLAIM_GRANTED")
                journal._db.execute("INSERT INTO workflow_authority_decisions VALUES(?,?,?,?,?)", (
                    "CLAIM", "run", claim_id, decision_digest, canonical(claim_decision),
                ))
                raise RuntimeError("claim fixture rollback")
            self.assertEqual(journal.snapshot("scope"), before_claim)
            self.assertIsNone(journal._db.execute(
                "SELECT 1 FROM workflow_authority_decisions WHERE decision_kind='CLAIM' AND run_id='run'"
            ).fetchone())
            with journal._transaction():
                self.assertEqual(_claim_in_transaction(
                    journal, "scope", native.operation_id, native.binding_digest, claim_id,
                ), "CLAIM_GRANTED")
                journal._db.execute("INSERT INTO workflow_authority_decisions VALUES(?,?,?,?,?)", (
                    "CLAIM", "run", claim_id, decision_digest, canonical(claim_decision),
                ))
            self.assertEqual(journal._db.execute(
                "SELECT decision_digest,payload FROM workflow_authority_decisions "
                "WHERE decision_kind='CLAIM' AND run_id='run' AND operation_or_claim_id=?", (claim_id,),
            ).fetchone()[:], (decision_digest, canonical(claim_decision)))
            self.assertEqual(journal.claim("scope", "native", native.binding_digest, "claim:legacy"), "DENY")

    def test_v6_adopted_run_before_policy_effect_keeps_ordinary_financial_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(
            Path(directory) / "ordinary.db", WRITER, storage_version=6,
        ) as journal:
            _, _, policy, _ = ClosingResourceCandidateTests._inputs()
            self.assertEqual(journal.open_scope(
                BudgetScope("scope", "run", "tokens"), policy,
                OpeningBalance("opening", "source", "tokens", {}, 0, (), WRITER, WRITER),
            ), "OPENED")
            binding = self._binding(journal)
            binding["storageProtocolVersion"] = "6"
            with journal._transaction():
                journal._db.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", (
                    "run", canonical_digest(binding), canonical(binding),
                ))
            ordinary = replace(
                operation("scope", name="pre-effect", task=None, upper=1),
                run_id="run", unit_definition_id="tokens",
            )
            self.assertEqual(journal.reserve(ordinary, expected_revision=1), "RESERVED")
            self.assertEqual(journal.claim(
                "scope", "pre-effect", ordinary.binding_digest, "claim:pre-effect",
            ), "CLAIM_GRANTED")

    def test_v6_proof_body_stage_exact_bytes_hash_anchor_and_ack_denial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v6-stage.db"
            with Journal(path, WRITER, storage_version=6) as journal:
                binding = self._binding(journal)
                binding["storageProtocolVersion"] = "6"
                journal._db.execute(
                    "INSERT INTO workflow_bindings VALUES(?,?,?)",
                    ("run", canonical_digest(binding), canonical(binding)),
                )
                anchor = {
                    "schemaVersion": "agent-run-output-anchor.v1", "runId": "run",
                    "bindingDigest": canonical_digest(binding), "adoptedStateDigest": "b" * 64,
                    "journalIdentity": journal.journal_identity, "storageProtocolVersion": "6",
                    "artifactAuthorityRootPath": str(Path(directory) / "root"),
                    "artifactAuthorityRootIdentity": {"platform": "POSIX", "volumeId": "volume", "fileId": "file"},
                    "canonicalStatePath": "state.json", "packageRoot": "package",
                    "resolvedPackageRootRelativePath": "package", "eventLog": "events.jsonl",
                    "runOutputRootRelativePath": ".alk-closing/run",
                }
                anchor_bytes = canonical(anchor).encode("utf-8")
                anchor_digest = hashlib.sha256(anchor_bytes).hexdigest()
                journal._db.execute(
                    "INSERT INTO workflow_run_output_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("run", anchor["bindingDigest"], "b" * 64, journal.journal_identity,
                     anchor["artifactAuthorityRootPath"], "POSIX", "volume", "file", "package",
                     "events.jsonl", ".alk-closing/run", anchor_bytes, anchor_digest, 6),
                )
                prepared = canonical({"schemaVersion": "fixture-prepared.v1", "operationId": "produce"}).encode()
                body = canonical({"schemaVersion": "fixture-body.v1", "result": "ok"}).encode()
                row = [
                    "run", "produce", "c" * 64, anchor_digest,
                    prepared, len(prepared), hashlib.sha256(prepared).hexdigest(),
                    body, hashlib.sha256(body).hexdigest(), len(body),
                    b"{}", b"{}", b"{}", "PENDING", None,
                ]
                sql = "INSERT INTO workflow_proof_body_stage VALUES(" + ",".join("?" for _ in row) + ")"
                for index in (3, 5, 6, 8, 9, 13, 14):
                    with self.subTest(column=index):
                        altered = row.copy()
                        altered[index] = "ACK" if index == 13 else "wrong"
                        with self.assertRaises(sqlite3.IntegrityError):
                            journal._db.execute(sql, altered)
                        self.assertEqual(journal._db.execute(
                            "SELECT COUNT(*) FROM workflow_proof_body_stage"
                        ).fetchone()[0], 0)
                for index, counterpart in ((4, 6), (7, 8)):
                    with self.subTest(noncanonical=index):
                        altered = row.copy()
                        altered[index] = b'{ "noncanonical":true}'
                        altered[counterpart] = hashlib.sha256(altered[index]).hexdigest()
                        if index == 4:
                            altered[5] = len(altered[index])
                        else:
                            altered[9] = len(altered[index])
                        with self.assertRaises(sqlite3.IntegrityError):
                            journal._db.execute(sql, altered)
                journal._db.execute(sql, row)
                with self.assertRaises(sqlite3.IntegrityError):
                    journal._db.execute(
                        "UPDATE workflow_proof_body_stage SET publication_status='ACK',ack_digest=? "
                        "WHERE run_id='run' AND producer_operation_id='produce'", ("d" * 64,)
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    journal._db.execute("UPDATE workflow_proof_body_stage SET body_bytes=?", (b"{}",))
                with self.assertRaises(sqlite3.IntegrityError):
                    journal._db.execute("DELETE FROM workflow_proof_body_stage")
            with Journal(path, WRITER, storage_version=6) as reopened:
                saved = reopened._db.execute(
                    "SELECT prepared_input_bytes,body_bytes,publication_status FROM workflow_proof_body_stage"
                ).fetchone()
                self.assertEqual(tuple(saved), (prepared, body, "PENDING"))

    def test_unregistered_or_old_writer_cannot_write_workflow_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.db"
            with Journal(path, WRITER):
                pass
            binding = ("run", "b" * 64, "{}")
            with sqlite3.connect(path, isolation_level=None) as unregistered, self.assertRaises(sqlite3.OperationalError):
                unregistered.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", binding)
            with sqlite3.connect(path, isolation_level=None) as old:
                old.create_function("alk_storage_writer_version", 0, lambda: 4)
                with self.assertRaises(sqlite3.IntegrityError):
                    old.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", binding)

    def test_missing_workflow_guard_refuses_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.db"
            with Journal(path, WRITER):
                pass
            with sqlite3.connect(path) as db:
                db.execute("DROP TRIGGER guard_workflow_nonce_uses_insert")
            with self.assertRaises(JournalUnavailable):
                Journal(path, WRITER)

    def test_pinned_read_and_reconcile_do_not_advance_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "new.db", WRITER) as journal:
            binding, state = self._binding(journal), self._state()
            pin = canonical_digest(binding)
            store = WorkflowStore(journal, binding, pin)
            with self.assertRaises(JournalUnavailable):
                store.read_run()
            with journal._transaction():
                journal._db.execute(
                    "INSERT INTO workflow_bindings VALUES(?,?,?)", ("run", pin, canonical(binding))
                )
                journal._db.execute(
                    "INSERT INTO workflow_states VALUES(?,?,?,?,?)",
                    ("run", 1, digest(state), canonical(state), 1),
                )
                journal._db.execute(
                    "INSERT INTO workflow_projection_outbox VALUES(?,?,?,?,?,?,?)",
                    ("run", 1, digest(state), "d" * 64, "{}", "PENDING", None),
                )
                journal._db.execute(
                    "INSERT INTO workflow_transitions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("run", "op", "e" * 64, 0, 1, digest({"ok": True}), canonical({"ok": True}), None, None, None),
                )
            self.assertEqual(store.read_run()["publicationStatus"], "PENDING")
            self.assertEqual(store.reconcile_operation("missing", "e" * 64), {"status": "NOT_COMMITTED"})
            self.assertEqual(store.reconcile_operation("op", "f" * 64), {"status": "CONFLICT"})
            result = store.reconcile_operation("op", "e" * 64)
            self.assertEqual((result["status"], result["result"], result["publicationStatus"]),
                             ("COMMITTED", {"ok": True}, "PENDING"))
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_transitions").fetchone()[0], 1)

    def test_committed_replay_survives_unavailable_projection_without_new_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "new.db", WRITER) as journal:
            binding, state = self._binding(journal), self._state()
            store = WorkflowStore(journal, binding, canonical_digest(binding))
            result = {"status": "historical-result", "nativePermissionGranted": False}
            with journal._transaction():
                journal._db.execute(
                    "INSERT INTO workflow_bindings VALUES(?,?,?)",
                    ("run", canonical_digest(binding), canonical(binding)),
                )
                journal._db.execute(
                    "INSERT INTO workflow_states VALUES(?,?,?,?,?)",
                    ("run", 1, digest(state), canonical(state), 1),
                )
                journal._db.execute(
                    "INSERT INTO workflow_transitions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("run", "old-op", "e" * 64, 0, 1, digest(result), canonical(result), None, None, None),
                )
            before = journal._db.total_changes
            with self.assertRaises(JournalUnavailable):
                store.read_run()
            replay = store.reconcile_operation("old-op", "e" * 64)
            self.assertEqual(replay, {
                "status": "COMMITTED", "result": result, "resultDigest": digest(result),
                "publicationStatus": "UNAVAILABLE",
            })
            self.assertEqual(store.reconcile_operation("old-op", "f" * 64), {"status": "CONFLICT"})
            self.assertEqual(store.reconcile_operation("missing", "e" * 64), {"status": "NOT_COMMITTED"})
            self.assertEqual(journal._db.total_changes, before)
            with journal._transaction():
                journal._db.execute(
                    "INSERT INTO workflow_projection_outbox VALUES(?,?,?,?,?,?,?)",
                    ("run", 1, digest(state), "d" * 64, "[]", "PENDING", None),
                )
            before = journal._db.total_changes
            with self.assertRaises(JournalUnavailable):
                store.read_run()
            self.assertEqual(store.reconcile_operation("old-op", "e" * 64)["publicationStatus"], "UNAVAILABLE")
            self.assertEqual(journal._db.total_changes, before)
            with journal._transaction():
                journal._db.execute(
                    "INSERT INTO workflow_transitions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("run", "future-op", "f" * 64, 1, 2, digest(result), canonical(result), None, None, None),
                )
            with self.assertRaises(JournalUnavailable):
                store.reconcile_operation("future-op", "f" * 64)

    def test_unqualified_adoption_refuses_before_journal_or_artifact_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "new.db", WRITER) as journal:
            before = journal._db.total_changes
            result = WorkflowStore.adopt_run(
                journal, {"operatorQualification": "QUALIFIED_LOCAL_OPERATOR"},
                {"callerSelectedRoot": True}, artifact_root=Path(directory) / "missing",
                observed_at="2026-09-23T00:00:00.000000Z",
            )
            self.assertEqual(result, {
                "status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED",
            })
            self.assertEqual(journal._db.total_changes, before)
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_adoptions").fetchone()[0], 0)
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_roots").fetchone()[0], 0)
            self.assertFalse((Path(directory) / "missing").exists())
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_transitions").fetchone()[0], 0)

    def test_unqualified_transition_refuses_before_artifact_or_journal_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "new.db", WRITER) as journal:
            binding = self._binding(journal)
            store = WorkflowStore(journal, binding, canonical_digest(binding))
            before = journal._db.total_changes
            request = {"operatorQualification": "QUALIFIED", "action": "activateClosingWindow"}
            for method in (
                "commit_transition", "admission_context", "reserve_closing_operation",
                "claim_with_workflow_authority", "authorize_local_proof_production",
            ):
                with self.subTest(method=method):
                    kwargs = {"artifact_root": Path(directory) / "missing"} if method == "commit_transition" else {}
                    result = getattr(store, method)(request, **kwargs)
                    self.assertEqual(result, {
                        "status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED",
                    })
                    self.assertEqual(journal._db.total_changes, before)
            self.assertEqual(journal._db.total_changes, before)
            for table in (
                "workflow_transitions", "workflow_windows", "workflow_nonce_uses",
                "closing_policy_effects", "workflow_projection_outbox",
            ):
                self.assertEqual(journal._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            self.assertFalse((Path(directory) / "missing").exists())

    def test_binding_requires_independent_digest_and_same_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "new.db", WRITER) as journal:
            binding = self._binding(journal)
            with self.assertRaises(JournalUnavailable):
                WorkflowStore(journal, binding, "0" * 64)
            changed = dict(binding, journalIdentity="other")
            with self.assertRaises(JournalUnavailable):
                WorkflowStore(journal, changed, canonical_digest(changed))
            invalid = dict(binding, resourceInventoryRef={"path": "pin.json", "sha256": "c" * 64, "bytes": True})
            with self.assertRaises(JournalUnavailable):
                WorkflowStore(journal, invalid, canonical_digest(invalid))

    @unittest.skipIf(os.name == "nt", "Windows does not rename an open SQLite database")
    def test_read_refuses_replaced_journal_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.db"
            with Journal(path, WRITER) as journal:
                binding = self._binding(journal)
                store = WorkflowStore(journal, binding, canonical_digest(binding))
                moved = path.with_suffix(".moved")
                path.rename(moved)
                path.write_bytes(moved.read_bytes())
                with self.assertRaises(JournalUnavailable):
                    store.read_run()

    def test_read_after_journal_close_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / "new.db", WRITER)
            binding = self._binding(journal)
            store = WorkflowStore(journal, binding, canonical_digest(binding))
            journal.close()
            with self.assertRaises(JournalUnavailable):
                store.read_run()

    def test_explicit_v4_migration_is_atomic_and_fenced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            self._v4(path)
            before = path.read_bytes()
            with self.assertRaises(JournalUnavailable):
                Journal(path, WRITER)
            self.assertEqual(path.read_bytes(), before)

            for fault_point in ("before_version", "after_version"):
                def fault(point: str, selected: str = fault_point) -> None:
                    if point == selected:
                        raise RuntimeError("injected migration failure")

                with self.assertRaises(RuntimeError):
                    Journal.migrate_v4(path, WRITER, fault_hook=fault)
                self.assertEqual(path.read_bytes(), before)
            Journal.migrate_v4(path, WRITER)
            with Journal(path, WRITER) as journal:
                self.assertEqual(journal._db.execute("SELECT version FROM schema_metadata").fetchone()[0], 5)
                Journal._validate_schema(journal._db, 5)
            with self.assertRaises(JournalUnavailable):
                Journal.migrate_v4(path, WRITER)

    def test_ds24_unmigrated_v5_financial_continuity_and_protected_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with Journal(path, WRITER) as journal:
                open_scope(journal)
                settled = operation(name="settled", upper=100)
                late = operation(name="late", upper=100)
                self.assertEqual(journal.reserve(settled), "RESERVED")
                self.assertEqual(journal.claim("run", "settled", settled.binding_digest, "claim:settled"), "CLAIM_GRANTED")
                self.assertEqual(journal.record_settlement(receipt(settled, 30)), "SETTLED")
                self.assertEqual(journal.reserve(late), "RESERVED")
                self.assertEqual(journal.claim("run", "late", late.binding_digest, "claim:late"), "CLAIM_GRANTED")
                prior = journal.snapshot("run")
                history = _financial_snapshot_digest(journal._db)
                schema = _storage_schema_digest(journal._db)
                self.assertIsNone(journal._db.execute(
                    "SELECT name FROM sqlite_master WHERE name='workflow_storage_migrations'"
                ).fetchone())
            with Journal(path, WRITER) as journal:
                self.assertEqual(journal.snapshot("run"), prior)
                self.assertEqual(_financial_snapshot_digest(journal._db), history)
                self.assertEqual(_storage_schema_digest(journal._db), schema)
                self.assertEqual(journal.record_settlement(receipt(late, 40)), "SETTLED")
                self.assertEqual(journal.snapshot("run").known_spent, 70)
                self.assertEqual(journal.import_opening(*import_data("v5-retained")).status, "IMPORTED")
                retained = operation(scope="v5-retained", name="retained")
                self.assertEqual(journal.reserve(retained), "RESERVED")
                self.assertEqual(journal.claim(
                    "v5-retained", retained.operation_id, retained.binding_digest, "claim:retained"
                ), "CLAIM_GRANTED")
                self.assertEqual(journal.ingest_usage(
                    "v5-retained", observation([retained], [9], event="v5-final")
                ).status, "SETTLED")
                now = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
                closure = RunClosure(
                    "closure:v5-retained", "v5-retained", "reportedTokens:fixture:v1", now,
                    (("v5-retained", journal.snapshot("v5-retained").journal_revision),), WRITER, WRITER,
                )
                closed = journal.close_run(closure, now)
                self.assertEqual(journal.collect_closed_run("v5-retained", now).status, "NOT_DUE")
                self.assertEqual(journal.collect_closed_run("v5-retained", closed.eligible_after).status, "COLLECTED")
                self.assertEqual(journal.ingest_usage(
                    "v5-retained", observation([retained], [10], event="v5-correction")
                ).status, "ACCOUNTING_RECONCILIATION_REQUIRED")
                before = journal._db.total_changes
                result = WorkflowStore.adopt_run(
                    journal, {"operatorQualification": "QUALIFIED_LOCAL_OPERATOR"},
                    {"callerSelectedRoot": True}, artifact_root=Path(directory) / "missing",
                    observed_at="2026-09-23T00:00:00.000000Z",
                )
                self.assertEqual(result["reason"], "UNSUPPORTED_OPERATOR_ROUTE")
                self.assertEqual(journal._db.total_changes, before)
            with self.assertRaises(JournalUnavailable):
                Journal(path, WRITER, storage_version=6)

    def test_ds25_v5_to_v6_faults_roll_back_and_preserve_financial_rows(self) -> None:
        for point in ("before_version", "after_version", "after_receipt", "before_commit"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "legacy.db"
                with Journal(path, WRITER) as journal:
                    open_scope(journal)
                    paid = operation(name="paid")
                    pending = operation(name="pending")
                    self.assertEqual(journal.reserve(paid), "RESERVED")
                    self.assertEqual(journal.claim("run", "paid", paid.binding_digest, "claim:paid"), "CLAIM_GRANTED")
                    self.assertEqual(journal.record_settlement(receipt(paid, 25)), "SETTLED")
                    self.assertEqual(journal.reserve(pending), "RESERVED")
                    before_snapshot = journal.snapshot("run")
                    before_financial = _financial_snapshot_digest(journal._db)
                    before_schema = _storage_schema_digest(journal._db)
                before_bytes = path.read_bytes()

                def fail(at: str, selected: str = point) -> None:
                    if at == selected:
                        raise RuntimeError("injected v5-to-v6 failure")

                with self.assertRaises(RuntimeError):
                    Journal._migrate_v5_storage_fixture(path, WRITER, fault_hook=fail)
                self.assertEqual(path.read_bytes(), before_bytes)
                with Journal(path, WRITER) as journal:
                    self.assertEqual(journal.snapshot("run"), before_snapshot)
                    self.assertEqual(_financial_snapshot_digest(journal._db), before_financial)
                    self.assertEqual(_storage_schema_digest(journal._db), before_schema)
                    self.assertEqual(journal.claim("run", "pending", pending.binding_digest, "claim:pending"), "CLAIM_GRANTED")
                    self.assertEqual(journal.record_settlement(receipt(pending, 35)), "SETTLED")

    def test_ds25_every_nonempty_workflow_or_authority_table_refuses_migration(self) -> None:
        inventory = [(table, "PENDING") for table in (*WORKFLOW_TABLES, *AUTHORITY_TABLES)]
        inventory.append(("workflow_projection_outbox", "ACK"))
        for table, outbox_status in inventory:
            with self.subTest(table=table, outbox_status=outbox_status), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "legacy.db"
                with Journal(path, WRITER) as journal:
                    open_scope(journal)
                    op = operation(name="historical")
                    self.assertEqual(journal.reserve(op), "RESERVED")
                    self.assertEqual(journal.claim("run", op.operation_id, op.binding_digest, "claim:historical"), "CLAIM_GRANTED")
                    self.assertEqual(journal.record_settlement(receipt(op, 17)), "SETTLED")
                    parents = journal._db.execute(f"PRAGMA foreign_key_list({table})").fetchall()
                    if table != "workflow_bindings" and any(p[2] == "workflow_bindings" for p in parents):
                        binding = self._binding(journal)
                        journal._db.execute(
                            "INSERT INTO workflow_bindings VALUES(?,?,?)",
                            ("run", canonical_digest(binding), canonical(binding)),
                        )
                    columns = journal._db.execute(f"PRAGMA table_info({table})").fetchall()
                    values = []
                    for column in columns:
                        name, kind = column[1], column[2]
                        if not column[3] and not column[5]:
                            values.append(None)
                        elif kind == "INTEGER":
                            values.append(1 if name == "after_revision" else 0)
                        elif name == "status":
                            values.append(outbox_status)
                        elif name in {"payload", "state_json", "result_json"}:
                            values.append("{}")
                        elif name == "run_id":
                            values.append("run")
                        else:
                            values.append("x")
                    if table != "workflow_bindings":
                        journal._db.execute(
                            f"INSERT INTO {table} VALUES({','.join('?' for _ in values)})", values,
                        )
                    else:
                        journal._db.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", ("run", "a" * 64, "{}"))
                    self.assertFalse(journal._db.execute("PRAGMA foreign_key_check").fetchall())
                    self.assertEqual(journal._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
                before = path.read_bytes()
                with self.assertRaises(JournalUnavailable):
                    Journal._migrate_v5_storage_fixture(path, WRITER)
                self.assertEqual(path.read_bytes(), before)
                with Journal(path, WRITER) as reopened:
                    self.assertEqual(reopened.snapshot("run").known_spent, 17)

    def test_ds26_v6_financial_late_retention_exception_and_resource_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with Journal(path, WRITER) as journal:
                open_scope(journal)
                late = operation(name="late")
                self.assertEqual(journal.reserve(late), "RESERVED")
                self.assertEqual(journal.claim("run", late.operation_id, late.binding_digest, "claim:late"), "CLAIM_GRANTED")
                before = journal.snapshot("run")
                self.assertEqual(journal.import_opening(*import_data("retained")).status, "IMPORTED")
                retained = operation(scope="retained", name="retained")
                self.assertEqual(journal.reserve(retained), "RESERVED")
                self.assertEqual(journal.claim(
                    "retained", retained.operation_id, retained.binding_digest, "claim:retained"
                ), "CLAIM_GRANTED")
            self.assertEqual(Journal._migrate_v5_storage_fixture(path, WRITER), "MIGRATED")
            with Journal(path, WRITER, storage_version=6) as journal:
                self.assertEqual(journal.snapshot("run"), before)
                self.assertEqual(journal.record_settlement(receipt(late, 40)), "SETTLED")
                new = operation(name="new")
                self.assertEqual(journal.reserve(new), "RESERVED")
                self.assertEqual(journal.claim("run", new.operation_id, new.binding_digest, "claim:new"), "CLAIM_GRANTED")
                self.assertEqual(journal.record_settlement(receipt(new, 20)), "SETTLED")
                self.assertEqual(journal.snapshot("run").known_spent, 60)
                binding = self._binding(journal)
                binding["storageProtocolVersion"] = "6"
                store = WorkflowStore(journal, binding, canonical_digest(binding))
                changes = journal._db.total_changes
                self.assertEqual(store.reserve_closing_operation({"fixture": True}), {
                    "status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED",
                })
                self.assertEqual(journal._db.total_changes, changes)
                self.assertEqual(journal.ingest_usage(
                    "retained", observation([retained], [10], event="retained-final")
                ).status, "SETTLED")
                now = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
                closure = RunClosure(
                    "closure:retained", "retained", "reportedTokens:fixture:v1", now,
                    (("retained", journal.snapshot("retained").journal_revision),), WRITER, WRITER,
                )
                closed = journal.close_run(closure, now)
                self.assertEqual(closed.status, "CLOSED")
                self.assertEqual(
                    datetime.fromisoformat(closed.eligible_after) - datetime.fromisoformat(now),
                    timedelta(days=30),
                )
                self.assertEqual(journal.collect_closed_run("retained", now).status, "NOT_DUE")
                self.assertEqual(journal.collect_closed_run("retained", closed.eligible_after).status, "COLLECTED")
                self.assertEqual(journal.history_metadata("retained")["status"], "DETAILS_COLLECTED")
                self.assertEqual(journal.snapshot("run").known_spent, 60)
                self.assertEqual(journal.ingest_usage(
                    "retained", observation([retained], [11], event="retained-correction")
                ).status, "ACCOUNTING_RECONCILIATION_REQUIRED")
                self.assertEqual(journal._db.execute(
                    "SELECT ordinal FROM exception_heads WHERE run_id='retained'"
                ).fetchone()[0], 1)

    def test_ds26_v6_resource_reserve_claim_share_one_storage_transaction(self) -> None:
        """A local SQL fixture proves atomic storage, not protected host permission."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "migrated-resource.db"
            inventory, proposal, before, anchor = ClosingResourceCandidateTests._inputs()
            with Journal(path, WRITER) as journal:
                inventory.update(budgetScopeId="scope", journalIdentity=journal.journal_identity, taskIds=[])
                proposal.update(
                    budgetScopeId="scope", journalIdentity=journal.journal_identity,
                    inventoryDigest=canonical_digest(inventory), expectedJournalRevision=1,
                    limits=proposal["limits"][:1],
                    protectionAllocations=proposal["protectionAllocations"][:1],
                )
                anchor["journalRevision"] = 1
                for field in ("spent", "reservations", "protected", "violationsByOwner"):
                    anchor[field] = {"": anchor[field][""]}
                self.assertEqual(journal.open_scope(
                    BudgetScope("scope", "run", "tokens"), before,
                    OpeningBalance("opening", "source", "tokens", {}, 120, (), WRITER, WRITER),
                ), "OPENED")
                historical = journal.snapshot("scope")
                self.assertEqual(open_scope(journal), "OPENED")
                late = operation(name="ds26-late")
                self.assertEqual(journal.reserve(late), "RESERVED")
                self.assertEqual(journal.claim("run", late.operation_id, late.binding_digest, "claim:late"),
                                 "CLAIM_GRANTED")
                ordinary_history = journal.snapshot("run")
                self.assertEqual(journal.import_opening(*import_data("retained")).status, "IMPORTED")
                retained = operation(scope="retained", name="ds26-retained")
                self.assertEqual(journal.reserve(retained), "RESERVED")
                self.assertEqual(journal.claim(
                    "retained", retained.operation_id, retained.binding_digest, "claim:retained"
                ), "CLAIM_GRANTED")
                retained_history = journal.snapshot("retained")
            self.assertEqual(Journal._migrate_v5_storage_fixture(path, WRITER), "MIGRATED")
            with Journal(path, WRITER, storage_version=6) as journal:
                self.assertEqual(journal.snapshot("scope"), historical)
                self.assertEqual(journal.snapshot("run"), ordinary_history)
                self.assertEqual(journal.snapshot("retained"), retained_history)
                self.assertEqual(journal.record_settlement(receipt(late, 40)), "SETTLED")
                ordinary = operation(name="ds26-ordinary")
                self.assertEqual(journal.reserve(ordinary), "RESERVED")
                self.assertEqual(journal.claim(
                    "run", ordinary.operation_id, ordinary.binding_digest, "claim:ordinary"
                ), "CLAIM_GRANTED")
                self.assertEqual(journal.record_settlement(receipt(ordinary, 20)), "SETTLED")
                self.assertEqual(journal.snapshot("run").known_spent, 60)
                self.assertEqual(journal.ingest_usage(
                    "retained", observation([retained], [10], event="ds26-retained-final")
                ).status, "SETTLED")
                now = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
                closure = RunClosure(
                    "closure:ds26-retained", "retained", "reportedTokens:fixture:v1", now,
                    (("retained", journal.snapshot("retained").journal_revision),), WRITER, WRITER,
                )
                closed = journal.close_run(closure, now)
                self.assertEqual(closed.status, "CLOSED")
                self.assertEqual(
                    datetime.fromisoformat(closed.eligible_after) - datetime.fromisoformat(now),
                    timedelta(days=30),
                )
                self.assertEqual(journal.collect_closed_run("retained", now).status, "NOT_DUE")
                self.assertEqual(journal.collect_closed_run("retained", closed.eligible_after).status, "COLLECTED")
                self.assertEqual(journal.history_metadata("retained")["status"], "DETAILS_COLLECTED")
                self.assertEqual(journal.ingest_usage(
                    "retained", observation([retained], [11], event="ds26-retained-correction")
                ).status, "ACCOUNTING_RECONCILIATION_REQUIRED")
                self.assertEqual(journal._db.execute(
                    "SELECT ordinal FROM exception_heads WHERE run_id='retained'"
                ).fetchone()[0], 1)
                derived = derive_policy_candidate_data(inventory, proposal, before, anchor)
                candidate = derived["candidate"]
                effect = {
                    "schemaVersion": "agent-closing-resource-effect.v1",
                    "candidateDigest": digest(candidate), "proposalDigest": digest(proposal),
                    "runId": "run", "budgetScopeId": "scope", "closingWindowId": "window",
                    "activationOperationId": "ds26-local-activation",
                    "authorityDecisionDigest": "a" * 64, "grantDigest": "b" * 64,
                    "beforeJournalRevision": 1, "afterJournalRevision": 2,
                    "beforePolicy": candidate["beforePolicy"], "afterPolicy": candidate["afterPolicy"],
                }
                effect_digest = digest(effect)
                record = {
                    "effect": effect, "candidate": candidate, "proposal": proposal,
                    "nativeBeforePolicy": asdict(before),
                    "nativeAfterPolicy": derived["nativeAfterPolicy"],
                }
                with journal._transaction():
                    state, revision = journal._load("scope")
                    journal._record("scope", state, revision, "CLOSING_POLICY_APPLIED", record)
                op = replace(
                    operation("scope", name="ds26-resource", task=None, upper=7, closeout=True),
                    run_id="run", policy_revision=2, unit_definition_id="tokens",
                )
                op_raw = canonical(asdict(op)).encode("utf-8")
                root = Path(directory) / "root"
                output = root / ".alk-closing/run"
                output.mkdir(parents=True)
                (output / "operation.json").write_bytes(op_raw)
                sidecar = {
                    "schemaVersion": "agent-closing-operation-binding.v1", "bindingId": "binding",
                    "runId": "run", "budgetScopeId": "scope", "closingWindowId": "window",
                    "policyEffectDigest": effect_digest, "operationId": op.operation_id,
                    "nativeOperationRef": {
                        "path": ".alk-closing/run/operation.json",
                        "sha256": hashlib.sha256(op_raw).hexdigest(), "bytes": len(op_raw),
                    },
                    "nativeOperationDigest": op.binding_digest, "action": "accounting-closeout",
                    "owner": {"scopeKind": "RUN", "taskId": None}, "unit": proposal["unit"],
                    "upperBound": 7, "expectedJournalRevision": 2,
                    "expectedWorkflowRevision": 1, "expectedAuthorityEpoch": 0,
                    "expectedGuardStateDigest": "f" * 64,
                }
                bucket = {
                    "schemaVersion": "agent-closing-protection-bucket.v1",
                    "budgetScopeId": "scope", "owner": {"scopeKind": "RUN", "taskId": None},
                    "originWindowId": "window", "unspent": 3,
                }
                binding = self._binding(journal)
                binding["storageProtocolVersion"] = "6"
                store = WorkflowStore(journal, binding, canonical_digest(binding))
                self.assertIs(store._journal._db, journal._db)
                before_resource = journal.snapshot("scope")
                before_sql = _financial_snapshot_digest(journal._db)
                schema_digest = _storage_schema_digest(journal._db)
                historical_rows = [tuple(row) for row in journal._db.execute(
                    "SELECT * FROM events WHERE scope='scope' AND revision<=2 ORDER BY revision,ordinal"
                )]
                self.assertEqual(store.reserve_closing_operation({})["status"], "DENY")
                self.assertEqual(store.claim_with_workflow_authority({})["status"], "DENY")
                with self.assertRaisesRegex(JournalUnavailable, "admitted transaction"):
                    _reserve_in_transaction(journal, op)
                with self.assertRaisesRegex(JournalUnavailable, "admitted transaction"):
                    _claim_in_transaction(journal, "scope", op.operation_id, op.binding_digest, "claim:ds26")

                def write_fixture() -> None:
                    db = store._journal._db
                    self.assertTrue(db.in_transaction)
                    self.assertEqual(journal._admission_depth, 1)
                    self.assertEqual(db.execute(
                        "SELECT alk_storage_writer_version(),version FROM schema_metadata WHERE singleton=1"
                    ).fetchone()[:], (6, 6))
                    self.assertEqual(_reserve_in_transaction(journal, op, expected_revision=2), "RESERVED")
                    self.assertEqual(_claim_in_transaction(
                        journal, "scope", op.operation_id, op.binding_digest, "claim:ds26",
                    ), "CLAIM_GRANTED")
                    state, revision = journal._load("scope")
                    balances = reconstruct_closing_balances(
                        state, revision, proposal, [sidecar], [bucket], effect_digest,
                    )
                    db.execute("INSERT INTO closing_policy_effects VALUES(?,?,?,?)", (
                        "run", "window", effect_digest, canonical(record),
                    ))
                    db.execute("INSERT INTO closing_operation_bindings VALUES(?,?,?,?)", (
                        "scope", op.operation_id, digest(sidecar), canonical(sidecar),
                    ))
                    db.execute("INSERT INTO closing_protection_buckets VALUES(?,?,?,?,?)", (
                        "scope", "", "window", revision, canonical(bucket),
                    ))
                    for balance in balances:
                        db.execute("INSERT INTO closing_resource_balances VALUES(?,?,?,?,?)", (
                            "scope", "window", balance["scope"]["taskId"] or "", revision,
                            canonical(balance),
                        ))

                with self.assertRaisesRegex(RuntimeError, "ds26 rollback"), store._journal._transaction():
                    write_fixture()
                    raise RuntimeError("ds26 rollback")
                self.assertEqual(journal.snapshot("scope"), before_resource)
                self.assertEqual(_financial_snapshot_digest(journal._db), before_sql)
                for table in (
                    "closing_policy_effects", "closing_operation_bindings",
                    "closing_protection_buckets", "closing_resource_balances",
                ):
                    self.assertEqual(journal._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
                with store._journal._transaction():
                    write_fixture()
                after_resource = journal.snapshot("scope")
                self.assertEqual(after_resource.known_spent, before_resource.known_spent)
                self.assertEqual(after_resource.active_reservations, 7)
                self.assertEqual(journal._load("scope")[0]["operations"][op.operation_id]["claim_id"], "claim:ds26")
                self.assertNotEqual(_financial_snapshot_digest(journal._db), before_sql)
                self.assertEqual(_storage_schema_digest(journal._db), schema_digest)
                self.assertEqual([tuple(row) for row in journal._db.execute(
                    "SELECT * FROM events WHERE scope='scope' AND revision<=2 ORDER BY revision,ordinal"
                )], historical_rows)
                self.assertEqual(journal._db.execute(
                    "SELECT COUNT(*) FROM closing_operation_bindings WHERE budget_scope_id='scope'"
                ).fetchone()[0], 1)
                self.assertEqual(journal._db.execute(
                    "SELECT COUNT(*) FROM closing_resource_balances WHERE budget_scope_id='scope'"
                ).fetchone()[0], 1)
                persisted = read_persisted_closing_balances(journal._db, binding, "window")
                self.assertEqual(persisted["status"], "CURRENT")
                self.assertEqual(len(persisted["balances"]), 1)
                balance = persisted["balances"][0]
                self.assertEqual(balance["currentKnownCumulativeSpent"], 120)
                self.assertEqual(balance["allActiveReservations"], 7)
                self.assertEqual(balance["windowActiveReservations"], 7)
                self.assertEqual(balance["globalProtected"], 3)
                self.assertFalse(persisted["financialAdmission"])
                self.assertEqual(store.claim_with_workflow_authority({})["status"], "DENY")
            with Journal(path, WRITER, storage_version=6) as reopened:
                self.assertEqual(_storage_schema_digest(reopened._db), schema_digest)
                self.assertEqual(read_persisted_closing_balances(
                    reopened._db, self._binding(reopened) | {"storageProtocolVersion": "6"}, "window",
                )["status"], "CURRENT")

    def test_ds27_migrated_receipt_reopen_and_old_writer_fence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fresh = Path(directory) / "fresh-v6.db"
            with Journal(fresh, WRITER, storage_version=6) as journal:
                self.assertEqual(journal._db.execute(
                    "SELECT migration_id,from_version,to_version FROM workflow_storage_migrations"
                ).fetchone()[:], ("init-v6", None, 6))
            with Journal(fresh, WRITER, storage_version=6):
                pass
            with self.assertRaises(JournalUnavailable):
                Journal(fresh, WRITER)
            path = Path(directory) / "legacy.db"
            with Journal(path, WRITER) as journal:
                open_scope(journal)
                paid = operation(name="paid")
                self.assertEqual(journal.reserve(paid), "RESERVED")
                self.assertEqual(journal.claim("run", "paid", paid.binding_digest, "claim:paid"), "CLAIM_GRANTED")
                self.assertEqual(journal.record_settlement(receipt(paid, 20)), "SETTLED")
                before = journal.snapshot("run")
                old_schema = _storage_schema_digest(journal._db)
                old_financial = _financial_snapshot_digest(journal._db)
            crashed = Path(directory) / "post-commit-exit.db"
            shutil.copy2(path, crashed)
            child = subprocess.run(
                [
                    sys.executable, "-c",
                    "import os, sys; "
                    "from agent_lifecycle.accounting.contracts import EvidenceRef; "
                    "from agent_lifecycle.accounting.journal import Journal; "
                    "Journal._migrate_v5_storage_fixture("
                    "sys.argv[1], EvidenceRef('test-writer', 'a' * 64), "
                    "fault_hook=lambda at: os._exit(73) if at == 'after_commit' else None); "
                    "os._exit(74)",
                    str(crashed),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(child.returncode, 73, child.stderr)
            with Journal(crashed, WRITER, storage_version=6) as recovered:
                self.assertEqual(recovered.snapshot("run"), before)
                self.assertEqual(_financial_snapshot_digest(recovered._db), old_financial)
                self.assertEqual(recovered._db.execute(
                    "SELECT migration_id,from_version,to_version FROM workflow_storage_migrations"
                ).fetchone()[:], ("v5-to-v6", 5, 6))
            self.assertEqual(Journal._migrate_v5_storage_fixture(crashed, WRITER), "ALREADY_MIGRATED")
            postcommit_error = Path(directory) / "post-commit-error.db"
            shutil.copy2(path, postcommit_error)

            def fail_after_commit(point: str) -> None:
                if point == "after_commit":
                    raise RuntimeError("post-commit fixture fault")

            with self.assertRaisesRegex(RuntimeError, "post-commit fixture fault"):
                Journal._migrate_v5_storage_fixture(postcommit_error, WRITER, fault_hook=fail_after_commit)
            with Journal(postcommit_error, WRITER, storage_version=6) as recovered:
                self.assertEqual(recovered.snapshot("run"), before)
                self.assertEqual(_financial_snapshot_digest(recovered._db), old_financial)
                self.assertEqual(recovered._db.execute(
                    "SELECT COUNT(*) FROM workflow_storage_migrations"
                ).fetchone()[0], 1)
            self.assertEqual(Journal._migrate_v5_storage_fixture(postcommit_error, WRITER), "ALREADY_MIGRATED")
            self.assertEqual(Journal._migrate_v5_storage_fixture(path, WRITER), "MIGRATED")
            with Journal(path, WRITER, storage_version=6) as journal:
                self.assertEqual(journal.snapshot("run"), before)
                self.assertEqual(_financial_snapshot_digest(journal._db), old_financial)
                row = journal._db.execute("SELECT * FROM workflow_storage_migrations").fetchone()
                self.assertEqual((row[1], row[2], row[3], row[4]), ("v5-to-v6", 5, 6, old_schema))
                self.assertEqual(row[5], _storage_schema_digest(journal._db))
                self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_storage_migrations").fetchone()[0], 1)
            self.assertEqual(Journal._migrate_v5_storage_fixture(path, WRITER), "ALREADY_MIGRATED")
            with Journal(path, WRITER, storage_version=6) as journal:
                self.assertEqual(journal._db.total_changes, 0)
                self.assertEqual(journal.snapshot("run"), before)
            with self.assertRaises(JournalUnavailable):
                Journal(path, WRITER)
            with sqlite3.connect(path, isolation_level=None) as old:
                old.create_function("alk_storage_writer_version", 0, lambda: 5)
                with self.assertRaises(sqlite3.IntegrityError):
                    old.execute("INSERT INTO workflow_bindings VALUES(?,?,?)", ("stale", "a" * 64, "{}"))
            for corruption in ("missing-receipt", "bad-digest"):
                with self.subTest(corruption=corruption):
                    altered = Path(directory) / (corruption + ".db")
                    shutil.copy2(path, altered)
                    with sqlite3.connect(altered, isolation_level=None) as tamper:
                        action = "delete" if corruption == "missing-receipt" else "update"
                        trigger_name = f"protect_workflow_storage_migrations_{action}"
                        trigger = tamper.execute(
                            "SELECT sql FROM sqlite_master WHERE name=?", (trigger_name,)
                        ).fetchone()[0]
                        tamper.execute(f"DROP TRIGGER {trigger_name}")
                        if corruption == "missing-receipt":
                            tamper.execute("DELETE FROM workflow_storage_migrations")
                        else:
                            tamper.execute(
                                "UPDATE workflow_storage_migrations SET new_schema_digest=?", ("0" * 64,)
                            )
                        tamper.execute(trigger)
                    with self.assertRaises(JournalUnavailable):
                        Journal(altered, WRITER, storage_version=6)
            with sqlite3.connect(path, isolation_level=None) as tamper:
                tamper.execute("DROP TRIGGER guard_workflow_bindings_insert")
            with self.assertRaises(JournalUnavailable):
                Journal(path, WRITER, storage_version=6)


if __name__ == "__main__":
    unittest.main()
