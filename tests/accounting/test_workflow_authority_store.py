"""Successor snapshots remain serialized under an already qualified root fixture."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from agent_lifecycle.accounting.contracts import EvidenceRef, canonical
from agent_lifecycle.accounting.journal import Journal, JournalUnavailable
from agent_lifecycle.accounting.workflow_authority_store import install_successor_snapshot
from agent_lifecycle.accounting.workflow_state_store import WorkflowStore
from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_authority_schemas import (
    AUTHORITY_INPUT_BUNDLE_V1,
    AUTHORITY_SNAPSHOT_V1,
    INSTALL_SNAPSHOT_REQUEST_V1,
)
from tests.contracts.test_workflow_authority import _grant, _issuer, _pin, _signed

WRITER = EvidenceRef("test-writer", "a" * 64)
DOMAIN = b"agent-lifecycle-workflow-authority-snapshot-v1\x00"
ROOT_SEED = bytes(range(32))


def _rotation_process(path: str, binding: dict, request: dict, artifact_root: str) -> dict:
    with Journal(Path(path), WRITER) as journal:
        store = WorkflowStore(journal, binding, canonical_digest(binding))
        snapshot = json.loads((Path(artifact_root) / request["snapshotRef"]["path"]).read_text())
        with journal._transaction():
            store._require_binding(journal._db)
            return install_successor_snapshot(
                journal._db, store._binding, store._binding_digest,
                snapshot, request["operationId"], request["expectedAuthorityEpoch"],
            )


class WorkflowAuthorityStoreTests(unittest.TestCase):
    def test_signed_grant_data_join_is_transaction_bound_and_never_native_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            state = {
                "schemaVersion": "agent-workflow-state.v4", "runId": "run", "packageId": "package",
                "planRevision": 1, "planDigest": "a" * 64, "sourceRevision": "source",
                "stateRevision": 1, "phase": "RUNNING", "eventLog": "events.jsonl",
                "operationLedger": {},
                "tasks": [{"id": "WS-01", "status": "READY", "attempt": 0, "dependsOn": [],
                           "attemptHistory": [], "required": True}],
            }
            with journal._transaction():
                journal._db.execute(
                    "INSERT INTO workflow_states VALUES(?,?,?,?,?)",
                    ("run", 1, canonical_digest(state), canonical(state), 1),
                )
            pin = json.loads(journal._db.execute(
                "SELECT payload FROM workflow_authority_roots WHERE binding_id=?", ("binding",),
            ).fetchone()[0])["pin"]
            window_intent = {
                "schemaVersion": "agent-closing-window-request.v1", "closingWindowId": "window",
                "nonce": "a" * 64, "runId": "run", "sourceRevision": "source",
            }
            grant = _signed({
                **_grant(), "scope": {
                    **_grant()["scope"], "journalIdentity": journal.journal_identity,
                    "originalPlanDigest": "a" * 64, "effectivePlanDigest": "a" * 64,
                },
                "windowIntentDigest": canonical_digest(window_intent),
                "validFrom": "2020-01-01T00:00:00.000000Z",
                "expiresAt": "2100-01-01T00:00:00.000000Z",
                "issuedUnderEpoch": 0, "issuedUnderSnapshotDigest": canonical_digest(initial),
                "expectedWorkflowRevision": 1,
            }, bytes(range(1, 33)), b"agent-lifecycle-workflow-closing-grant-v1\x00")
            raw = canonical(grant).encode("utf-8")
            ref = {"path": "fixture-grant.json", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            window = {**window_intent, "ownerPermissionRef": "sha256:" + canonical_digest(grant)}
            window_raw = canonical(window).encode("utf-8")
            window_ref = {
                "path": "fixture-window.json", "sha256": hashlib.sha256(window_raw).hexdigest(),
                "bytes": len(window_raw),
            }
            selected = {
                "schemaVersion": AUTHORITY_INPUT_BUNDLE_V1, "bindingId": "binding",
                "pinDigest": canonical_digest(pin), "grantRef": ref,
                "issuanceSnapshotDigest": canonical_digest(initial), "expectedCurrentEpoch": 0,
                "windowRequestRef": window_ref, "resourceApprovalRef": ref,
                "allowedWritesRef": ref, "deadlineInputRef": ref,
            }
            authority_input_raw = canonical(selected).encode("utf-8")
            authority_ref = {
                "path": "fixture-authority.json", "sha256": hashlib.sha256(authority_input_raw).hexdigest(),
                "bytes": len(authority_input_raw),
            }
            effect = {
                "closingWindowId": grant["closingWindowId"], "authorityDomain": grant["authorityDomain"],
                "issuerId": grant["issuerId"], "issuerGeneration": grant["issuerGeneration"],
                "nonce": grant["nonce"], "commitBoundAuthorityRef": ref,
                "qualifiedPolicyEffectRef": ref, "windowRequestRef": window_ref,
            }
            transition = {
                "schemaVersion": "agent-workflow-transition-request.v1",
                "binding": {"bindingId": "binding", "expectedBindingDigest": store._binding_digest},
                "operationId": "activate", "expectedWorkflowRevision": 1,
                "expectedAccountingRevisions": [], "action": "activateClosingWindow",
                "eventType": "closing-window-activated", "nextStateRef": ref,
                "eventBundleRef": ref, "semanticResultRef": ref,
                "authorityContextRef": authority_ref, "activationEffect": effect,
                "preparedProofInputRef": None,
            }
            transition["requestDigest"] = canonical_digest(transition)
            observed = {
                "schemaVersion": "agent-workflow-clock-observation.v1",
                "journalIdentity": journal.journal_identity, "processIdentity": "fixture-process",
                "observedAt": "2099-01-01T00:00:00.000000Z", "monotonicNanos": 1,
                "monotonicOriginId": "fixture-origin",
                "previousAcceptedUtc": "2020-01-01T00:00:00.000000Z",
                "clockQualificationDigest": "a" * 64,
            }
            with self.assertRaises(JournalUnavailable):
                store._signed_grant_data_in_transaction(selected, raw, observed)
            before = journal._db.total_changes
            with journal._transaction():
                result = store._signed_grant_data_in_transaction(selected, raw, observed)
                self.assertEqual(result["status"], "DATA_CANDIDATE")
                self.assertEqual(result["grantDigest"], canonical_digest(grant))
                self.assertTrue(result["rawGrantRefVerified"])
                self.assertTrue(result["grantSignatureVerifiedAtSuppliedTime"])
                self.assertTrue(result["effectivePlanVerified"])
                self.assertTrue(result["workflowRevisionVerified"])
                for name in ("rootQualificationVerified", "historyQualified", "clockQualified",
                             "grantQualified", "nonceConsumed", "nativePermissionGranted"):
                    self.assertFalse(result[name])
                joined = store._activation_intent_data_in_transaction(
                    transition, selected, authority_input_raw, raw, window_raw, observed,
                )
                self.assertTrue(joined["transitionRequestDigestVerified"])
                self.assertTrue(joined["windowIntentDigestVerified"])
                self.assertFalse(joined["windowRequestShapeVerified"])
                for name in ("resourcePolicyEffectRefVerified", "resourceApprovalRefVerified",
                             "allowedWritesRefVerified", "deadlineInputRefVerified"):
                    self.assertFalse(joined[name])
                self.assertFalse(joined["nativePermissionGranted"])
            self.assertEqual(journal._db.total_changes, before)
            for bad_request, bad_window_raw in (
                ({**transition, "requestDigest": "0" * 64}, window_raw),
                (transition, window_raw + b" "),
            ):
                with self.assertRaises(JournalUnavailable), journal._transaction():
                    store._activation_intent_data_in_transaction(
                        bad_request, selected, authority_input_raw, raw, bad_window_raw, observed,
                    )
            bad_effect_request = {
                **transition, "activationEffect": {**effect, "issuerId": "different-issuer"},
            }
            bad_effect_request["requestDigest"] = canonical_digest({
                name: value for name, value in bad_effect_request.items() if name != "requestDigest"
            })
            with self.assertRaises(JournalUnavailable), journal._transaction():
                store._activation_intent_data_in_transaction(
                    bad_effect_request, selected, authority_input_raw, raw, window_raw, observed,
                )
            wrong_owner = {**window, "ownerPermissionRef": "sha256:" + "0" * 64}
            wrong_raw = canonical(wrong_owner).encode("utf-8")
            wrong_ref = {**window_ref, "sha256": hashlib.sha256(wrong_raw).hexdigest(),
                         "bytes": len(wrong_raw)}
            wrong_selected = {**selected, "windowRequestRef": wrong_ref}
            wrong_authority_raw = canonical(wrong_selected).encode("utf-8")
            wrong_authority_ref = {
                **authority_ref, "sha256": hashlib.sha256(wrong_authority_raw).hexdigest(),
                "bytes": len(wrong_authority_raw),
            }
            wrong_transition = {
                **transition, "authorityContextRef": wrong_authority_ref,
                "activationEffect": {**effect, "windowRequestRef": wrong_ref},
            }
            wrong_transition["requestDigest"] = canonical_digest({
                name: value for name, value in wrong_transition.items() if name != "requestDigest"
            })
            with self.assertRaises(JournalUnavailable), journal._transaction():
                store._activation_intent_data_in_transaction(
                    wrong_transition, wrong_selected, wrong_authority_raw, raw, wrong_raw, observed,
                )
            for bad_raw, bad_clock in (
                (raw + b" ", observed),
                (raw, {**observed, "previousAcceptedUtc": "2021-01-01T00:00:00.000000Z"}),
                (raw, {**observed, "observedAt": "2019-01-01T00:00:00.000000Z"}),
            ):
                with self.assertRaises(JournalUnavailable), journal._transaction():
                    store._signed_grant_data_in_transaction(selected, bad_raw, bad_clock)
            self.assertEqual(journal._db.total_changes, before)
            successor = self._successor(initial)
            request = self._request(Path(directory), successor, "revoke", 0)
            self.assertEqual(store.install_authority_snapshot(request, artifact_root=Path(directory))["status"],
                             "INSTALLED")
            observed["previousAcceptedUtc"] = journal._db.execute(
                "SELECT accepted_utc FROM workflow_clock_high_water WHERE journal_identity=?",
                (journal.journal_identity,),
            ).fetchone()[0]
            with self.assertRaises(JournalUnavailable), journal._transaction():
                store._signed_grant_data_in_transaction({**selected, "expectedCurrentEpoch": 1}, raw, observed)

    def test_persisted_authority_candidate_is_read_only_and_not_a_grant(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            root_record = json.loads(journal._db.execute(
                "SELECT payload FROM workflow_authority_roots WHERE binding_id=?", ("binding",),
            ).fetchone()[0])
            ref = {"path": "unread.json", "sha256": "a" * 64, "bytes": 1}
            selected = {
                "schemaVersion": AUTHORITY_INPUT_BUNDLE_V1, "bindingId": "binding",
                "pinDigest": canonical_digest(root_record["pin"]), "grantRef": ref,
                "issuanceSnapshotDigest": canonical_digest(initial), "expectedCurrentEpoch": 0,
                "windowRequestRef": ref, "resourceApprovalRef": ref,
                "allowedWritesRef": ref, "deadlineInputRef": ref,
            }
            before = journal._db.total_changes
            result = store.read_current_authority_candidate(selected)
            self.assertEqual(result["status"], "DATA_CANDIDATE")
            self.assertEqual(result["currentSnapshotDigest"], canonical_digest(initial))
            self.assertTrue(result["historyCryptoVerified"])
            for name in ("rootQualificationVerified", "historyQualified", "clockQualified",
                         "grantQualified", "nonceConsumed", "nativePermissionGranted"):
                self.assertFalse(result[name])
            self.assertEqual(journal._db.total_changes, before)
            self.assertFalse((Path(directory) / "unread.json").exists())
            with self.assertRaises(JournalUnavailable):
                store.read_current_authority_candidate({**selected, "expectedCurrentEpoch": 1})
            with self.assertRaises(JournalUnavailable):
                store.read_current_authority_candidate({**selected, "pinDigest": "0" * 64})
            successor = self._successor(initial)
            request = self._request(Path(directory), successor, "revoke", 0)
            self.assertEqual(store.install_authority_snapshot(request, artifact_root=Path(directory))["status"],
                             "INSTALLED")
            after_revocation = store.read_current_authority_candidate({
                **selected, "expectedCurrentEpoch": 1,
            })
            self.assertEqual(after_revocation["currentSnapshotDigest"], canonical_digest(successor))
            self.assertEqual(after_revocation["issuanceSnapshotDigest"], canonical_digest(initial))
            self.assertFalse(after_revocation["grantQualified"])

    def test_authority_candidate_refuses_broken_intermediate_predecessor(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            successor = self._successor(initial)
            self.assertEqual(self._install(store, Path(directory), successor, "first", 0)["status"],
                             "INSTALLED")
            pin = json.loads(journal._db.execute(
                "SELECT payload FROM workflow_authority_roots WHERE binding_id=?", ("binding",),
            ).fetchone()[0])["pin"]
            bad_tip = _signed({
                **successor, "epoch": 2, "previousSnapshotDigest": canonical_digest(initial),
            }, ROOT_SEED, DOMAIN)
            with journal._transaction():
                journal._db.execute(
                    "INSERT INTO workflow_authority_snapshots VALUES(?,?,?,?,?,?)",
                    ("binding", 2, canonical_digest(bad_tip), canonical_digest(initial),
                     "corrupt-fixture", canonical(bad_tip)),
                )
                journal._db.execute(
                    "UPDATE workflow_authority_current SET epoch=?,snapshot_digest=? WHERE binding_id=?",
                    (2, canonical_digest(bad_tip), "binding"),
                )
            ref = {"path": "unread.json", "sha256": "a" * 64, "bytes": 1}
            selected = {
                "schemaVersion": AUTHORITY_INPUT_BUNDLE_V1, "bindingId": "binding",
                "pinDigest": canonical_digest(pin), "grantRef": ref,
                "issuanceSnapshotDigest": canonical_digest(initial), "expectedCurrentEpoch": 2,
                "windowRequestRef": ref, "resourceApprovalRef": ref,
                "allowedWritesRef": ref, "deadlineInputRef": ref,
            }
            with self.assertRaises(JournalUnavailable):
                store.read_current_authority_candidate(selected)

    @staticmethod
    def _request(root: Path, snapshot: dict, operation_id: str, expected_epoch: int) -> dict:
        raw = canonical(snapshot).encode("utf-8")
        checksum = hashlib.sha256(raw).hexdigest()
        name = f"{checksum}.json"
        path = root / name
        if not path.exists():
            path.write_bytes(raw)
        return {
            "schemaVersion": "agent-workflow-authority-install.v1",
            "bindingId": "binding", "operationId": operation_id,
            "expectedAuthorityEpoch": expected_epoch,
            "snapshotRef": {"path": name, "sha256": checksum, "bytes": len(raw)},
        }

    @classmethod
    def _install(cls, store: WorkflowStore, root: Path, snapshot: dict, operation_id: str, expected_epoch: int) -> dict:
        cls._request(root, snapshot, operation_id, expected_epoch)
        with store._journal._transaction():
            store._require_binding(store._journal._db)
            return install_successor_snapshot(
                store._journal._db, store._binding, store._binding_digest,
                snapshot, operation_id, expected_epoch,
            )

    @staticmethod
    def _successor(initial: dict) -> dict:
        return _signed({
            **initial, "epoch": 1, "previousSnapshotDigest": canonical_digest(initial),
            "revokedGrants": [{"issuerId": "issuer", "issuerGeneration": "generation:1", "nonce": "a" * 64}],
        }, ROOT_SEED, DOMAIN)

    def _fixture(self, journal: Journal, *, seed_root: bool = True) -> tuple[WorkflowStore, dict]:
        ref = {"path": "pin.json", "sha256": "c" * 64, "bytes": 10}
        binding = {
            "schemaVersion": "agent-workflow-journal-binding.v1", "bindingId": "binding", "runId": "run",
            "packageId": "package", "budgetScopeId": "budget:run", "canonicalStatePath": "state.json",
            "journalPath": str(journal._path), "journalIdentity": journal.journal_identity,
            "storageProtocolVersion": "5", "workflowProtocolVersion": "1", "planDigest": "a" * 64,
            "sourceRevision": "source", "adoptionEpoch": "epoch-1", "authorityMode": "JOURNAL_REQUIRED",
            "workflowAuthorityPinRef": ref, "resourceInventoryRef": ref, "deadlineInventoryRef": ref,
        }
        issuer = {
            **_issuer(), "validFrom": "2020-01-01T00:00:00.000000Z",
            "expiresAt": "2100-01-01T00:00:00.000000Z",
            "scope": {
                **_issuer()["scope"], "journalIdentity": journal.journal_identity,
                "originalPlanDigest": "a" * 64, "effectivePlanDigest": "a" * 64,
            },
        }
        initial = _signed({
            "schemaVersion": AUTHORITY_SNAPSHOT_V1, "authorityDomain": "authority:run",
            "rootId": "root", "rootGeneration": "generation:1", "bindingId": "binding",
            "journalIdentity": journal.journal_identity, "epoch": 0, "previousSnapshotDigest": None,
            "validFrom": "2020-01-01T00:00:00.000000Z", "expiresAt": "2100-01-01T00:00:00.000000Z",
            "activeIssuers": [issuer], "revokedIssuers": [], "revokedGrants": [],
        }, ROOT_SEED, DOMAIN)
        pin = {**_pin(), "journalIdentity": journal.journal_identity,
               "expectedInitialSnapshotDigest": canonical_digest(initial)}
        pin_record = {"pin": pin, "pinRef": ref, "bindingDigest": canonical_digest(binding),
                      "qualificationDigest": pin["qualificationRef"]["sha256"]}
        with journal._transaction():
            journal._db.execute(
                "INSERT INTO workflow_bindings VALUES(?,?,?)",
                ("run", canonical_digest(binding), canonical(binding)),
            )
            if seed_root:
                journal._db.execute(
                    "INSERT INTO workflow_authority_roots VALUES(?,?,?)",
                    ("binding", canonical_digest(pin), canonical(pin_record)),
                )
                journal._db.execute(
                    "INSERT INTO workflow_authority_snapshots VALUES(?,?,?,?,?,?)",
                    ("binding", 0, canonical_digest(initial), None, "bootstrap", canonical(initial)),
                )
                journal._db.execute(
                    "INSERT INTO workflow_authority_current VALUES(?,?,?,?)",
                    ("binding", 0, canonical_digest(initial), "2020-01-01T00:00:00.000000Z"),
                )
                journal._db.execute(
                    "INSERT INTO workflow_clock_high_water VALUES(?,?)",
                    (journal.journal_identity, "2020-01-01T00:00:00.000000Z"),
                )
        return WorkflowStore(journal, binding, canonical_digest(binding)), initial

    def test_signed_successor_replay_and_revocation_monotonicity(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            successor = self._successor(initial)
            tampered = {**successor, "validFrom": "2021-01-01T00:00:00.000000Z"}
            self.assertEqual(
                self._install(store, Path(directory), tampered, "tampered", 0)["status"],
                "DENY",
            )
            first = self._install(store, Path(directory), successor, "rotation-1", 0)
            self.assertEqual(first["status"], "INSTALLED")
            replay = self._install(store, Path(directory), successor, "rotation-1", 0)
            self.assertEqual(replay["status"], "INSTALLED_REPLAY")
            conflict = self._install(store, Path(directory), successor, "other", 0)
            self.assertEqual(conflict["status"], "CONFLICT")
            rollback = _signed({**successor, "epoch": 2, "previousSnapshotDigest": canonical_digest(successor),
                                "revokedGrants": []}, ROOT_SEED, DOMAIN)
            denied = self._install(store, Path(directory), rollback, "rotation-2", 1)
            self.assertEqual(denied["status"], "DENY")
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_snapshots").fetchone()[0], 2)

    def test_lost_reply_after_commit_replays_original_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            successor = self._successor(initial)

            def fault(point: str) -> None:
                if point == "after_commit":
                    raise RuntimeError("lost response after durable commit")

            journal.fault_hook = fault
            with self.assertRaises(RuntimeError):
                self._install(store, Path(directory), successor, "rotation-1", 0)
            journal.fault_hook = None
            replay = self._install(store, Path(directory), successor, "rotation-1", 0)
            self.assertEqual(replay["status"], "INSTALLED_REPLAY")
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_snapshots").fetchone()[0], 2)

    def test_clock_rollback_refuses_snapshot_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            with journal._transaction():
                journal._db.execute(
                    "UPDATE workflow_clock_high_water SET accepted_utc=? WHERE journal_identity=?",
                    ("2099-01-01T00:00:00.000000Z", journal.journal_identity),
                )
            with self.assertRaises(JournalUnavailable):
                self._install(store, Path(directory), self._successor(initial), "rotation-1", 0)
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_snapshots").fetchone()[0], 1)

    def test_process_contenders_cannot_both_install_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "journal.db"
            with Journal(path, WRITER) as journal:
                store, initial = self._fixture(journal)
                binding = dict(store._binding)
            first = self._successor(initial)
            second = _signed({**first, "revokedGrants": [
                {"issuerId": "issuer", "issuerGeneration": "generation:1", "nonce": "b" * 64},
            ]}, ROOT_SEED, DOMAIN)
            requests = (self._request(root, first, "first", 0), self._request(root, second, "second", 0))
            with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
                results = list(pool.map(_rotation_process, [str(path)] * 2, [binding] * 2, requests,
                                        [str(root)] * 2))
            self.assertEqual([x["status"] for x in results].count("INSTALLED"), 1)
            self.assertEqual([x["status"] for x in results].count("CONFLICT"), 1)
            with Journal(path, WRITER) as journal:
                self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_snapshots").fetchone()[0], 2)

    def test_missing_bootstrap_cannot_self_select_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal, seed_root=False)
            forged = _signed({**initial, "epoch": 1, "previousSnapshotDigest": canonical_digest(initial)},
                             ROOT_SEED, DOMAIN)
            with self.assertRaises(JournalUnavailable):
                self._install(store, Path(directory), forged, "forged", 0)

    def test_public_install_refuses_new_issuer_with_existing_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            self.assertEqual(get_schema(INSTALL_SNAPSHOT_REQUEST_V1)["$id"], INSTALL_SNAPSHOT_REQUEST_V1)
            root = Path(directory)
            successor = self._successor(initial)
            expanded = _signed({**successor, "activeIssuers": [
                successor["activeIssuers"][0], {**successor["activeIssuers"][0], "issuerId": "new-issuer"},
            ]}, ROOT_SEED, DOMAIN)
            extended = _signed({**successor, "expiresAt": "2200-01-01T00:00:00.000000Z"}, ROOT_SEED, DOMAIN)
            before = journal._db.total_changes
            for name, snapshot in (("expansion", expanded), ("extension", extended)):
                with self.subTest(name=name):
                    request = self._request(root, snapshot, name, 0)
                    self.assertEqual(store.install_authority_snapshot(request, artifact_root=root), {
                        "status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE",
                    })
                    self.assertEqual(journal._db.total_changes, before)
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_snapshots").fetchone()[0], 1)

    def test_public_signed_revocation_remains_a_safety_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, initial = self._fixture(journal)
            root = Path(directory)
            request = self._request(root, self._successor(initial), "revoke", 0)
            self.assertEqual(store.install_authority_snapshot(request, artifact_root=root)["status"], "INSTALLED")
            self.assertEqual(store.install_authority_snapshot(request, artifact_root=root)["status"],
                             "INSTALLED_REPLAY")
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_snapshots").fetchone()[0], 2)

    def test_initial_root_request_refuses_current_operator_before_artifact_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            store, _ = self._fixture(journal, seed_root=False)
            before = journal._db.total_changes
            request = {
                "schemaVersion": INSTALL_SNAPSHOT_REQUEST_V1, "bindingId": "binding",
                "operationId": "bootstrap-attempt", "expectedAuthorityEpoch": None,
                "snapshotRef": {"path": "missing.json", "sha256": "0" * 64, "bytes": 1},
            }
            result = store.install_authority_snapshot(request, artifact_root=Path(directory))
            self.assertEqual(result, {
                "status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED",
            })
            self.assertEqual(journal._db.total_changes, before)
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_roots").fetchone()[0], 0)
            self.assertEqual(journal._db.execute("SELECT COUNT(*) FROM workflow_authority_snapshots").fetchone()[0], 0)
            self.assertFalse((Path(directory) / "missing.json").exists())

    def test_immutable_bootstrap_record_rejects_erasure(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            self._fixture(journal)
            with self.assertRaises(JournalUnavailable), journal._transaction():
                journal._db.execute("DELETE FROM workflow_authority_roots")
