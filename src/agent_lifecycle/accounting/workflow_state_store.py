"""WorkflowStore state port and unchanged historical journal delta codec."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.canonical import canonical_digest, load_json_object
from agent_lifecycle.contracts.deadline_schemas import utc_microseconds, validate_clock_observation
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_authority import (
    verify_signed_authority_snapshot,
    verify_signed_window_grant,
)
from agent_lifecycle.contracts.workflow_authority_schemas import (
    validate_authority_input_bundle,
    validate_authority_snapshot_shape,
    validate_install_snapshot_request,
)
from agent_lifecycle.contracts.workflow_state_schemas import (
    validate_adoption_selection,
    validate_runtime_binding,
    validate_transition_request,
    validate_workflow_state,
)

from .closing_resource_recovery import (
    _read_acknowledged_closing_operation_data,
    _read_current_closing_resource_data,
)
from .contracts import (
    PROTECTED_STORAGE_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION,
    JournalHandle,
    JournalUnavailable,
    _local_identity,
    _projection,
    canonical,
    digest,
)
from .workflow_authority_store import (
    AUTHORITY_TABLES,
    _loaded_root,
    _monotonic_successor,
    _snapshot_row,
    create_v6_workflow_extension,
    install_successor_snapshot,
)
from .workflow_authority_store import (
    prepare_legacy_adoption_candidate as prepare_legacy_adoption_candidate,
)
from .workflow_authority_store import (
    validate_legacy_adoption_history as validate_legacy_adoption_history,
)

WORKFLOW_TABLES = {
    "workflow_bindings": (
        "run_id TEXT PRIMARY KEY NOT NULL, binding_digest TEXT NOT NULL, payload TEXT NOT NULL",
        False,
    ),
    "workflow_states": (
        "run_id TEXT PRIMARY KEY NOT NULL REFERENCES workflow_bindings(run_id), "
        "revision INTEGER NOT NULL CHECK(revision>=0), state_digest TEXT NOT NULL, "
        "state_json TEXT NOT NULL, projection_generation INTEGER NOT NULL CHECK(projection_generation>=0)",
        True,
    ),
    "workflow_transitions": (
        "run_id TEXT NOT NULL REFERENCES workflow_bindings(run_id), operation_id TEXT NOT NULL, "
        "request_digest TEXT NOT NULL, before_revision INTEGER NOT NULL CHECK(before_revision>=0), "
        "after_revision INTEGER NOT NULL CHECK(after_revision>before_revision), result_digest TEXT NOT NULL, "
        "result_json TEXT NOT NULL, window_id TEXT, nonce_digest TEXT, policy_effect_digest TEXT, "
        "PRIMARY KEY(run_id,operation_id)",
        False,
    ),
    "workflow_events": (
        "run_id TEXT NOT NULL REFERENCES workflow_bindings(run_id), revision INTEGER NOT NULL CHECK(revision>=0), "
        "event_index INTEGER NOT NULL CHECK(event_index>=0), event_digest TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(run_id,revision,event_index)",
        False,
    ),
    "workflow_nonce_uses": (
        "authority_domain TEXT NOT NULL, issuer_id TEXT NOT NULL, issuer_generation INTEGER NOT NULL "
        "CHECK(issuer_generation>=0), nonce TEXT NOT NULL, run_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
        "request_digest TEXT NOT NULL, window_id TEXT, "
        "PRIMARY KEY(authority_domain,issuer_id,issuer_generation,nonce)",
        False,
    ),
    "workflow_windows": (
        "run_id TEXT NOT NULL REFERENCES workflow_bindings(run_id), closing_window_id TEXT NOT NULL, "
        "grant_digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,closing_window_id)",
        False,
    ),
    "workflow_projection_outbox": (
        "run_id TEXT NOT NULL REFERENCES workflow_bindings(run_id), generation INTEGER NOT NULL CHECK(generation>=0), "
        "state_digest TEXT NOT NULL, event_digest TEXT NOT NULL, payload TEXT NOT NULL, "
        "status TEXT NOT NULL CHECK(status IN ('PENDING','ACK')), ack_digest TEXT, "
        "PRIMARY KEY(run_id,generation)",
        True,
    ),
    "workflow_adoptions": (
        "run_id TEXT NOT NULL REFERENCES workflow_bindings(run_id), adoption_epoch INTEGER NOT NULL "
        "CHECK(adoption_epoch>=0), adoption_digest TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(run_id,adoption_epoch)",
        False,
    ),
    "closing_policy_effects": (
        "run_id TEXT NOT NULL, closing_window_id TEXT NOT NULL, effect_digest TEXT NOT NULL, "
        "payload TEXT NOT NULL, PRIMARY KEY(run_id,closing_window_id)",
        False,
    ),
    "closing_operation_bindings": (
        "budget_scope_id TEXT NOT NULL, operation_id TEXT NOT NULL, binding_digest TEXT NOT NULL, "
        "payload TEXT NOT NULL, PRIMARY KEY(budget_scope_id,operation_id)",
        False,
    ),
    "closing_resource_balances": (
        "budget_scope_id TEXT NOT NULL, closing_window_id TEXT NOT NULL, owner TEXT NOT NULL, "
        "generation INTEGER NOT NULL CHECK(generation>=0), payload TEXT NOT NULL, "
        "PRIMARY KEY(budget_scope_id,closing_window_id,owner)",
        True,
    ),
    "closing_protection_buckets": (
        "budget_scope_id TEXT NOT NULL, owner TEXT NOT NULL, origin_window_id TEXT NOT NULL, "
        "generation INTEGER NOT NULL CHECK(generation>=0), payload TEXT NOT NULL, "
        "PRIMARY KEY(budget_scope_id,owner,origin_window_id)",
        True,
    ),
    "workflow_clock_high_water": (
        "journal_identity TEXT PRIMARY KEY NOT NULL, accepted_utc TEXT NOT NULL",
        True,
    ),
    "workflow_deadline_decisions": (
        "decision_kind TEXT NOT NULL, run_id TEXT NOT NULL, operation_or_claim_id TEXT NOT NULL, "
        "decision_digest TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(decision_kind,run_id,operation_or_claim_id)",
        False,
    ),
}


def create_workflow_schema(db: sqlite3.Connection, *, writer_version: int) -> None:
    """Install exact workflow guards for an explicitly selected storage version."""
    if writer_version not in (STORAGE_SCHEMA_VERSION, PROTECTED_STORAGE_SCHEMA_VERSION):
        raise ValueError("Unsupported workflow storage writer")
    for table, (columns, mutable) in (*WORKFLOW_TABLES.items(), *AUTHORITY_TABLES.items()):
        db.execute(f"CREATE TABLE {table}({columns})")
        db.execute(
            f"CREATE TRIGGER guard_{table}_insert BEFORE INSERT ON {table} "
            f"WHEN alk_storage_writer_version() IS NOT {writer_version} OR "
            f"(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT {writer_version} "
            "BEGIN SELECT RAISE(ABORT,'incompatible workflow writer'); END"
        )
        for action in ("UPDATE", "DELETE"):
            if not mutable or action == "DELETE":
                db.execute(
                    f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END"
                )
            else:
                db.execute(
                    f"CREATE TRIGGER guard_{table}_{action.lower()} BEFORE {action} ON {table} "
                    f"WHEN alk_storage_writer_version() IS NOT {writer_version} OR "
                    f"(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT {writer_version} "
                    "BEGIN SELECT RAISE(ABORT,'incompatible workflow writer'); END"
                )
    if writer_version == PROTECTED_STORAGE_SCHEMA_VERSION:
        create_v6_workflow_extension(db)


STATE_DELTA_CODEC = "ALK_STATE_DELTA_V1"


def _state_delta(before: dict | None, after: dict) -> dict:
    """Encode only changed dictionary paths; arrays remain atomic JSON values."""
    if (before is not None and not isinstance(before, dict)) or not isinstance(after, dict):
        raise JournalUnavailable("Scope state must be a dictionary")
    changes = []

    def visit(old: dict, new: dict, path: list[str]) -> None:
        for key in sorted(old.keys() | new.keys()):
            child = [*path, key]
            if key not in new:
                changes.append({"op": "remove", "path": child})
            elif key not in old:
                changes.append({"op": "add", "path": child, "value": copy.deepcopy(new[key])})
            elif isinstance(old[key], dict) and isinstance(new[key], dict):
                visit(old[key], new[key], child)
            elif (
                type(old[key]) in (str, int, bool, type(None))
                and type(old[key]) is type(new[key])
                and old[key] == new[key]
            ):
                # Full states were canonical-validated below before visit. Exact
                # built-in scalar types need no repeated JSON serialization.
                continue
            elif canonical(old[key]) != canonical(new[key]):
                # Python equality would incorrectly conflate true and 1, also in arrays.
                changes.append({"op": "replace", "path": child, "value": copy.deepcopy(new[key])})

    base_digest, result_digest = digest(before), digest(after)
    if before is None:
        changes.append({"op": "initialize", "path": [], "value": copy.deepcopy(after)})
    else:
        visit(before, after, [])
    return {"codec": STATE_DELTA_CODEC, "base_digest": base_digest, "result_digest": result_digest, "changes": changes}


def _apply_delta(before: dict | None, delta: dict) -> dict:
    """Strict replay on a copy. Neither corruption nor a failed patch alters before."""
    return _apply_delta_encoded(before, delta)[0]


def _apply_delta_encoded(before: dict | None, delta: dict) -> tuple[dict, str]:
    """Return replay and the exact canonical bytes checked by its result digest."""
    try:
        if (
            not isinstance(delta, dict)
            or set(delta) != {"codec", "base_digest", "result_digest", "changes"}
            or delta["codec"] != STATE_DELTA_CODEC
            or not isinstance(delta["changes"], list)
            or (before is not None and not isinstance(before, dict))
        ):
            raise JournalUnavailable("Malformed state delta")
        canonical(delta)  # Validate the full JSON domain, including values not yet applied.
        if delta["base_digest"] != digest(before):
            raise JournalUnavailable("State delta base mismatch")
        changes = delta["changes"]
        previous = None
        for change in changes:
            if not isinstance(change, dict) or change.get("op") not in {"initialize", "add", "replace", "remove"}:
                raise JournalUnavailable("Unknown state delta operation")
            expected = {"op", "path"} if change["op"] == "remove" else {"op", "path", "value"}
            if (
                set(change) != expected
                or not isinstance(change["path"], list)
                or not all(isinstance(key, str) for key in change["path"])
            ):
                raise JournalUnavailable("Malformed state delta operation")
            path = tuple(change["path"])
            if before is None:
                if len(changes) != 1 or change["op"] != "initialize" or path or not isinstance(change["value"], dict):
                    raise JournalUnavailable("Invalid state initialization")
            elif not path or change["op"] == "initialize":
                raise JournalUnavailable("Cannot reset an existing scope")
            if previous is not None and (path <= previous or path[: len(previous)] == previous):
                raise JournalUnavailable("Unsorted, duplicate or overlapping state paths")
            previous = path
        if before is None:
            if not changes:
                raise JournalUnavailable("Missing state initialization")
            result = copy.deepcopy(changes[0]["value"])
        else:
            result = copy.deepcopy(before)
            for change in changes:
                parent = result
                for key in change["path"][:-1]:
                    if key not in parent or not isinstance(parent[key], dict):
                        raise JournalUnavailable("Missing dictionary parent")
                    parent = parent[key]
                key = change["path"][-1]
                if (change["op"] == "add") == (key in parent):
                    raise JournalUnavailable("State delta key precondition failed")
                if change["op"] == "remove":
                    del parent[key]
                else:
                    parent[key] = copy.deepcopy(change["value"])
        encoded = canonical(result)
        if delta["result_digest"] != hashlib.sha256(encoded.encode("utf-8")).hexdigest():
            raise JournalUnavailable("State delta result mismatch")
        return result, encoded
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise JournalUnavailable("Invalid state delta encoding") from exc


class WorkflowStore:
    """Pinned read/reconcile port over one Journal; write operations require further gates."""

    @staticmethod
    def adopt_run(
        journal: object, adoption_input: dict, selection: dict,
        *, artifact_root: Path, observed_at: str,
    ) -> dict:
        """Refuse protected adoption until an independent operator route exists.

        The current Codex route has no protected root/Journal principal. Input
        artifacts, even signed ones, cannot upgrade it. This denial-only port
        performs no validation read, transaction, projection or dispatch.
        """
        del journal, adoption_input, selection, artifact_root, observed_at
        return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}

    def __init__(self, journal: object, binding: dict, expected_binding_digest: str) -> None:
        if not isinstance(journal, JournalHandle):
            raise JournalUnavailable("Existing Journal owner required", write_outcome="NOT_STARTED")
        try:
            validate_runtime_binding(binding)
            if (
                type(expected_binding_digest) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_binding_digest) is None
                or canonical_digest(binding) != expected_binding_digest
                or Path(binding["journalPath"]).resolve() != journal._path
                or binding["journalIdentity"] != journal.journal_identity
                or binding["storageProtocolVersion"] != str(journal._storage_version)
                or binding["workflowProtocolVersion"] != "1"
            ):
                raise JournalUnavailable("Runtime binding does not match pinned journal", write_outcome="NOT_STARTED")
        except (LifecycleError, OSError, TypeError, ValueError) as exc:
            raise JournalUnavailable("Invalid pinned runtime binding", write_outcome="NOT_STARTED") from exc
        self._journal = journal
        self._binding = copy.deepcopy(binding)
        self._binding_digest = expected_binding_digest

    @contextmanager
    def _read_snapshot(self) -> Iterator[sqlite3.Connection]:
        journal = self._journal
        journal._check_owner()
        db = journal._db
        try:
            if db.in_transaction:
                raise JournalUnavailable("Nested workflow read refused", write_outcome="NOT_STARTED")
            if _local_identity(journal._path) != journal._database_identity:
                raise JournalUnavailable("Journal identity changed", write_outcome="NOT_STARTED")
            db.execute("BEGIN")
            row = db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()
            if (
                row is None or row[0] != journal._storage_version
                or journal.journal_identity != self._binding["journalIdentity"]
            ):
                raise JournalUnavailable("Workflow journal version or identity changed", write_outcome="NOT_STARTED")
            yield db
        except (sqlite3.Error, OSError) as exc:
            raise JournalUnavailable("Authoritative workflow read unavailable", write_outcome="NOT_STARTED") from exc
        finally:
            try:
                if db.in_transaction:
                    db.execute("ROLLBACK")
            except sqlite3.Error as exc:
                raise JournalUnavailable("Workflow read cleanup unavailable", write_outcome="NOT_STARTED") from exc

    def _require_binding(self, db: sqlite3.Connection) -> None:
        run_id = self._binding["runId"]
        saved = db.execute("SELECT binding_digest,payload FROM workflow_bindings WHERE run_id=?", (run_id,)).fetchone()
        if saved is None or saved["binding_digest"] != self._binding_digest or saved["payload"] != canonical(self._binding):
            raise JournalUnavailable("Pinned workflow binding is absent or changed", write_outcome="NOT_STARTED")

    def _read_authoritative_state(self, db: sqlite3.Connection) -> tuple[dict, sqlite3.Row]:
        self._require_binding(db)
        run_id = self._binding["runId"]
        row = db.execute("SELECT * FROM workflow_states WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise JournalUnavailable("Authoritative workflow state is absent", write_outcome="NOT_STARTED")
        try:
            state = json.loads(row["state_json"])
            if canonical(state) != row["state_json"] or digest(state) != row["state_digest"]:
                raise ValueError("Workflow state digest mismatch")
            validate_workflow_state(state)
            if (
                state["runId"] != run_id
                or state["packageId"] != self._binding["packageId"]
                or state["planDigest"] != self._binding["planDigest"]
                or state["sourceRevision"] != self._binding["sourceRevision"]
                or state["stateRevision"] != row["revision"]
            ):
                raise ValueError("Workflow state binding or revision mismatch")
        except (KeyError, TypeError, ValueError, RecursionError, LifecycleError) as exc:
            raise JournalUnavailable("Invalid authoritative workflow state", write_outcome="NOT_STARTED") from exc
        return state, row

    def _publication_status(self, db: sqlite3.Connection, row: sqlite3.Row) -> str:
        run_id = self._binding["runId"]
        outbox = db.execute(
            "SELECT * FROM workflow_projection_outbox WHERE run_id=? AND generation=?",
            (run_id, row["projection_generation"]),
        ).fetchone()
        if (
            outbox is None
            or outbox["state_digest"] != row["state_digest"]
            or outbox["status"] not in {"ACK", "PENDING"}
            or (outbox["status"] == "ACK") != (outbox["ack_digest"] is not None)
            or type(outbox["event_digest"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", outbox["event_digest"]) is None
            or (outbox["ack_digest"] is not None and type(outbox["ack_digest"]) is not str)
            or (outbox["ack_digest"] is not None and re.fullmatch(r"[0-9a-f]{64}", outbox["ack_digest"]) is None)
        ):
            raise JournalUnavailable("Workflow publication identity is incomplete", write_outcome="NOT_STARTED")
        try:
            encoded = outbox["payload"]
            if type(encoded) is not str or len(encoded.encode("utf-8")) > 8_388_608:
                raise ValueError("Invalid projection payload encoding")
            payload = json.loads(encoded)
            if type(payload) is not dict or canonical(payload) != encoded:
                raise ValueError("Invalid projection payload")
        except (TypeError, ValueError, RecursionError) as exc:
            raise JournalUnavailable("Invalid workflow projection payload", write_outcome="NOT_STARTED") from exc
        return outbox["status"]

    def _read_run(self, db: sqlite3.Connection) -> dict:
        state, row = self._read_authoritative_state(db)
        publication_status = self._publication_status(db, row)
        return {
            "state": state,
            "revision": row["revision"],
            "projectionGeneration": row["projection_generation"],
            "publicationStatus": publication_status,
        }

    def read_run(self) -> dict:
        with self._read_snapshot() as db:
            return self._read_run(db)

    def commit_transition(self, request: dict, *, artifact_root: Path) -> dict:
        """Refuse protected workflow transitions on the current operator route.

        A request or its artifacts cannot qualify the process that owns this
        Journal. Until a separate operator route is proven, no transition,
        authority decision, policy effect, or projection may be written.
        """
        del request, artifact_root
        return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}

    def admission_context(self, request: dict) -> dict:
        """Do not turn a workflow read into a protected work permit on this route."""
        del request
        return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}

    def reserve_closing_operation(self, request: dict) -> dict:
        """Refuse new protected reservations without a qualified operator."""
        del request
        return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}

    def claim_with_workflow_authority(self, request: dict) -> dict:
        """Refuse protected dispatch claims before any financial or nonce effect."""
        del request
        return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}

    def authorize_local_proof_production(self, request: dict) -> dict:
        """Refuse protected proof production before a producer is launched."""
        del request
        return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}

    def read_adoption_accounting_candidate(self, selection: dict) -> dict:
        """Replay an existing qualified financial scope without creating allowance or adoption."""
        validate_adoption_selection(selection)
        if (
            selection["expectedBindingDigest"] != self._binding_digest
            or selection["expectedJournalIdentity"] != self._binding["journalIdentity"]
            or selection["expectedBudgetScopeId"] != self._binding["budgetScopeId"]
        ):
            raise JournalUnavailable("Selected accounting identity differs", write_outcome="NOT_STARTED")
        scope = self._binding["budgetScopeId"]
        with self._read_snapshot() as db:
            row = db.execute("SELECT data,revision FROM scope_state WHERE scope=?", (scope,)).fetchone()
            if row is None or row["revision"] != selection["expectedAccountingRevision"]:
                raise JournalUnavailable("Existing accounting revision differs", write_outcome="NOT_STARTED")
            replay, revision, _, _ = self._journal._live_facts(scope)
            if (
                revision != row["revision"]
                or canonical(replay) != row["data"]
                or digest(replay) != selection["expectedAccountingStateDigest"]
                or replay["scope"]["budget_scope_id"] != scope
                or replay["scope"]["run_id"] != self._binding["runId"]
                or type(replay["scope"].get("unit_definition_id")) is not str
                or not replay["scope"]["unit_definition_id"]
            ):
                raise JournalUnavailable("Existing accounting replay differs", write_outcome="NOT_STARTED")
            projection = _projection(replay, revision)
            if (
                not replay.get("opening_complete") or not replay.get("qualified")
                or replay.get("unresolved_reasons") or replay.get("input_unavailable")
                or projection.spent is None or projection.active_reservations is None
                or projection.protected_closeout is None
                or projection.gate_status not in {"READY", "BOUND_BROKEN"}
            ):
                raise JournalUnavailable("Existing accounting scope is not fully qualified", write_outcome="NOT_STARTED")
            return {
                "schemaVersion": "agent-workflow-adoption-accounting-candidate.v1",
                "status": "DATA_CANDIDATE", "budgetScopeId": scope,
                "runId": self._binding["runId"], "unitDefinitionId": replay["scope"]["unit_definition_id"],
                "revision": revision, "stateDigest": digest(replay),
                "knownSpent": projection.known_spent,
                "activeReservations": projection.active_reservations,
                "protectedCloseout": projection.protected_closeout,
                "gateStatus": projection.gate_status,
                "accountingReplayVerified": True, "accountingHistoryQualified": False,
                "operatorQualified": False, "quiescenceQualified": False,
                "financialAdmission": False, "nativePermissionGranted": False,
            }

    def read_current_authority_candidate(self, authority_input: dict) -> dict:
        """Read pinned signed authority history without a qualified clock or grant."""
        validate_authority_input_bundle(authority_input)
        if authority_input["bindingId"] != self._binding["bindingId"]:
            raise JournalUnavailable("Authority input binding differs", write_outcome="NOT_STARTED")
        with self._read_snapshot() as db:
            return self._select_authority_data(db, authority_input)[0]

    def _select_authority_data(self, db: sqlite3.Connection, authority_input: dict) -> tuple[dict, dict, dict, dict]:
        """Select one SQL epoch and its issuance record; caller owns the transaction."""
        validate_authority_input_bundle(authority_input)
        self._require_binding(db)
        pin = _loaded_root(db, self._binding, self._binding_digest)
        if canonical_digest(pin) != authority_input["pinDigest"]:
            raise JournalUnavailable("Selected root pin differs", write_outcome="NOT_STARTED")
        current_row = db.execute(
            "SELECT epoch,snapshot_digest,accepted_utc FROM workflow_authority_current WHERE binding_id=?",
            (self._binding["bindingId"],),
        ).fetchone()
        if current_row is None or current_row["epoch"] != authority_input["expectedCurrentEpoch"]:
            raise JournalUnavailable("Selected current authority epoch differs", write_outcome="NOT_STARTED")
        current, current_digest = _snapshot_row(db, self._binding["bindingId"], current_row["epoch"])
        if current_digest != current_row["snapshot_digest"]:
            raise JournalUnavailable("Current authority snapshot differs", write_outcome="NOT_STARTED")
        issuance_rows = db.execute(
            "SELECT epoch FROM workflow_authority_snapshots "
            "WHERE binding_id=? AND snapshot_digest=? LIMIT 2",
            (self._binding["bindingId"], authority_input["issuanceSnapshotDigest"]),
        ).fetchall()
        if len(issuance_rows) != 1 or issuance_rows[0]["epoch"] > current_row["epoch"]:
            raise JournalUnavailable("Grant issuance snapshot is absent or newer", write_outcome="NOT_STARTED")
        issuance, issuance_digest = _snapshot_row(
            db, self._binding["bindingId"], issuance_rows[0]["epoch"],
        )
        if issuance_digest != authority_input["issuanceSnapshotDigest"]:
            raise JournalUnavailable("Grant issuance snapshot differs", write_outcome="NOT_STARTED")
        try:
            chain = db.execute(
                "SELECT epoch,snapshot_digest,predecessor_digest FROM workflow_authority_snapshots "
                "WHERE binding_id=? AND epoch<=? ORDER BY epoch",
                (self._binding["bindingId"], current_row["epoch"]),
            ).fetchall()
            if len(chain) != current_row["epoch"] + 1:
                raise ValueError("Authority history has an epoch gap")
            previous = None
            previous_digest = None
            for expected_epoch, row in enumerate(chain):
                selected, selected_digest = _snapshot_row(db, self._binding["bindingId"], expected_epoch)
                if (
                    row["epoch"] != expected_epoch or selected["epoch"] != expected_epoch
                    or row["snapshot_digest"] != selected_digest
                    or row["predecessor_digest"] != previous_digest
                    or selected["previousSnapshotDigest"] != previous_digest
                    or (previous is not None and not _monotonic_successor(previous, selected))
                ):
                    raise ValueError("Authority history is not a monotonic predecessor chain")
                verify_signed_authority_snapshot(pin, selected, observed_at=selected["validFrom"])
                previous, previous_digest = selected, selected_digest
            if previous_digest != current_digest:
                raise ValueError("Authority chain tip differs")
        except (KeyError, TypeError, ValueError, LifecycleError) as exc:
            raise JournalUnavailable("Persisted authority history differs", write_outcome="NOT_STARTED") from exc
        candidate = {
            "schemaVersion": "agent-workflow-authority-sql-candidate.v1",
            "status": "DATA_CANDIDATE", "bindingId": self._binding["bindingId"],
            "pinDigest": authority_input["pinDigest"],
            "issuanceSnapshotDigest": issuance_digest,
            "currentSnapshotDigest": current_digest,
            "currentEpoch": current_row["epoch"],
            "persistedSignaturesVerified": True, "historyCryptoVerified": True,
            "rootQualificationVerified": False, "historyQualified": False,
            "clockQualified": False, "grantQualified": False,
            "nonceConsumed": False, "nativePermissionGranted": False,
        }
        return candidate, pin, issuance, current

    def _signed_grant_data_in_transaction(
        self, authority_input: dict, grant_raw: bytes, clock_observation: dict,
    ) -> dict:
        """Fixture-only data join under an admitted writer transaction; never a permit."""
        db = self._journal._db
        if not db.in_transaction or self._journal._admission_depth != 1:
            raise JournalUnavailable("Admitted authority transaction is required", write_outcome="NOT_STARTED")
        candidate, pin, issuance, current = self._select_authority_data(db, authority_input)
        state, state_row = self._read_authoritative_state(db)
        ref = authority_input["grantRef"]
        if (
            type(grant_raw) is not bytes or len(grant_raw) != ref["bytes"]
            or hashlib.sha256(grant_raw).hexdigest() != ref["sha256"]
        ):
            raise JournalUnavailable("Signed grant raw bytes differ from ref", write_outcome="NOT_STARTED")
        try:
            grant = load_json_object(grant_raw, label="signed closing grant")
            observation = validate_clock_observation(clock_observation)
            high = db.execute(
                "SELECT accepted_utc FROM workflow_clock_high_water WHERE journal_identity=?",
                (self._binding["journalIdentity"],),
            ).fetchone()
            selected = db.execute(
                "SELECT accepted_utc FROM workflow_authority_current WHERE binding_id=?",
                (self._binding["bindingId"],),
            ).fetchone()
            if (
                high is None or selected is None
                or observation["journalIdentity"] != self._binding["journalIdentity"]
                or observation["previousAcceptedUtc"] != high["accepted_utc"]
                or utc_microseconds(observation["observedAt"]) < utc_microseconds(selected["accepted_utc"])
            ):
                raise ValueError("Clock data differs from selected Journal high-water")
            for field in ("runId", "packageId", "budgetScopeId", "journalIdentity", "bindingId"):
                if grant["scope"][field] != self._binding[field]:
                    raise ValueError("Grant scope differs from pinned binding")
            if grant["scope"]["sourceRevision"] != self._binding["sourceRevision"]:
                raise ValueError("Grant source revision differs from pinned binding")
            if (
                grant["scope"]["effectivePlanDigest"] != state["planDigest"]
                or grant["expectedWorkflowRevision"] != state_row["revision"]
            ):
                raise ValueError("Grant plan or workflow revision differs from current SQL state")
            signed = verify_signed_window_grant(
                pin, issuance, current, grant, expected_scope=grant["scope"],
                observed_at=observation["observedAt"],
            )
        except (KeyError, TypeError, ValueError, LifecycleError) as exc:
            raise JournalUnavailable("Signed grant data join differs", write_outcome="NOT_STARTED") from exc
        return {
            **candidate, "schemaVersion": "agent-workflow-signed-grant-data-candidate.v1",
            "grantDigest": signed["grantDigest"], "rawGrantRefVerified": True,
            "grantSignatureVerifiedAtSuppliedTime": True, "clockDataConsistent": True,
            "effectivePlanVerified": True, "workflowRevisionVerified": True,
            "artifactPathVerified": False, "workflowScopeVerified": False,
            "rootQualificationVerified": False, "historyQualified": False,
            "clockQualified": False, "grantQualified": False,
            "nonceConsumed": False, "nativePermissionGranted": False,
        }

    def _read_acknowledged_closing_authority_data_in_transaction(
        self, sidecar: dict, authority_input: dict,
    ) -> dict:
        """Join saved operation and signed current epoch; never qualify its host."""
        operation_data = _read_acknowledged_closing_operation_data(self, sidecar)
        authority_data, _, _, _ = self._select_authority_data(self._journal._db, authority_input)
        if authority_data["currentEpoch"] != sidecar["expectedAuthorityEpoch"]:
            raise JournalUnavailable("Closing operation authority epoch is stale", write_outcome="NOT_STARTED")
        return {
            **operation_data, "authorityData": authority_data,
            "authorityEpoch": authority_data["currentEpoch"],
            "authorityHistoryCryptoVerified": True,
            "rootQualificationVerified": False, "clockQualified": False,
            "grantQualified": False, "financialAdmission": False,
            "nativePermissionGranted": False,
        }

    def _activation_intent_data_in_transaction(
        self, transition_request: dict, authority_input: dict, authority_input_raw: bytes,
        grant_raw: bytes, window_request_raw: bytes, clock_observation: dict,
    ) -> dict:
        """Join signed activation intent bytes without accepting a closing request or transition."""
        candidate = self._signed_grant_data_in_transaction(authority_input, grant_raw, clock_observation)
        try:
            request = validate_transition_request(transition_request)
            effect = request["activationEffect"]
            if effect is None:
                raise ValueError("Activation effect is absent")
            if (
                request["binding"]["bindingId"] != self._binding["bindingId"]
                or request["binding"]["expectedBindingDigest"] != self._binding_digest
                or request["expectedWorkflowRevision"] != self._read_authoritative_state(self._journal._db)[1]["revision"]
                or request["requestDigest"] != canonical_digest({
                    name: value for name, value in request.items() if name != "requestDigest"
                })
                or effect["commitBoundAuthorityRef"] != authority_input["grantRef"]
                or effect["windowRequestRef"] != authority_input["windowRequestRef"]
            ):
                raise ValueError("Transition identity or authority refs differ")
            authority_ref = request["authorityContextRef"]
            window_ref = authority_input["windowRequestRef"]
            if (
                type(authority_input_raw) is not bytes
                or len(authority_input_raw) != authority_ref["bytes"]
                or hashlib.sha256(authority_input_raw).hexdigest() != authority_ref["sha256"]
                or type(window_request_raw) is not bytes
                or len(window_request_raw) != window_ref["bytes"]
                or hashlib.sha256(window_request_raw).hexdigest() != window_ref["sha256"]
            ):
                raise ValueError("Authority or window raw bytes differ from refs")
            if load_json_object(authority_input_raw, label="activation authority input") != authority_input:
                raise ValueError("Authority input bytes differ from selected bundle")
            window = load_json_object(window_request_raw, label="closing window request")
            grant = load_json_object(grant_raw, label="signed closing grant")
            if (
                window.get("schemaVersion") != "agent-closing-window-request.v1"
                or window.get("ownerPermissionRef") != "sha256:" + candidate["grantDigest"]
                or window.get("closingWindowId") != grant["closingWindowId"]
                or window.get("nonce") != grant["nonce"]
                or candidate["grantDigest"] != canonical_digest(grant)
                or grant["windowIntentDigest"] != canonical_digest({
                    name: value for name, value in window.items() if name != "ownerPermissionRef"
                })
            ):
                raise ValueError("Signed closing intent differs from selected window bytes")
            for effect_field, grant_field in (
                ("closingWindowId", "closingWindowId"), ("authorityDomain", "authorityDomain"),
                ("issuerId", "issuerId"), ("issuerGeneration", "issuerGeneration"), ("nonce", "nonce"),
            ):
                if effect[effect_field] != grant[grant_field]:
                    raise ValueError("Activation effect differs from signed grant")
        except (KeyError, TypeError, ValueError, RecursionError, LifecycleError) as exc:
            raise JournalUnavailable("Activation intent data join differs", write_outcome="NOT_STARTED") from exc
        return {
            **candidate, "schemaVersion": "agent-workflow-activation-intent-data-candidate.v1",
            "transitionRequestDigestVerified": True, "authorityContextRawRefVerified": True,
            "activationGrantAndWindowRefsVerified": True, "windowRawRefVerified": True,
            "windowOwnerPermissionDigestVerified": True, "windowIntentDigestVerified": True,
            "windowRequestShapeVerified": False, "artifactPathVerified": False,
            "resourcePolicyEffectRefVerified": False, "resourceApprovalRefVerified": False,
            "allowedWritesRefVerified": False, "deadlineInputRefVerified": False,
            "grantQualified": False, "nativePermissionGranted": False,
        }

    def read_current_closing_resources(self, closing_window_id: str) -> dict:
        """Diagnose a pinned active window; a read never grants financial authority."""
        with self._read_snapshot() as db:
            current = self._read_run(db)
            return _read_current_closing_resource_data(db, self._binding, current, closing_window_id)

    def reconcile_operation(self, operation_id: str, request_digest: str) -> dict:
        if (
            type(operation_id) is not str
            or not 1 <= len(operation_id) <= 256
            or type(request_digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", request_digest) is None
        ):
            raise ValueError("Invalid workflow operation identity")
        with self._read_snapshot() as db:
            _, state_row = self._read_authoritative_state(db)
            row = db.execute(
                "SELECT * FROM workflow_transitions WHERE run_id=? AND operation_id=?",
                (self._binding["runId"], operation_id),
            ).fetchone()
            if row is None:
                return {"status": "NOT_COMMITTED"}
            if row["request_digest"] != request_digest:
                return {"status": "CONFLICT"}
            try:
                result = json.loads(row["result_json"])
                if (
                    canonical(result) != row["result_json"]
                    or digest(result) != row["result_digest"]
                    or row["after_revision"] > state_row["revision"]
                ):
                    raise ValueError("Transition result digest mismatch")
            except (TypeError, ValueError, RecursionError) as exc:
                raise JournalUnavailable("Invalid authoritative transition result", write_outcome="NOT_STARTED") from exc
            try:
                publication_status = self._publication_status(db, state_row)
            except JournalUnavailable:
                publication_status = "UNAVAILABLE"
            return {
                "status": "COMMITTED",
                "result": result,
                "resultDigest": row["result_digest"],
                "publicationStatus": publication_status,
            }

    def install_authority_snapshot(self, request: dict, *, artifact_root: Path) -> dict:
        """Allow only signed safety revocation; never bootstrap or expand authority."""
        try:
            selected_request = json.loads(canonical(request))
            validate_install_snapshot_request(selected_request)
        except (LifecycleError, TypeError, ValueError, RecursionError):
            return {"status": "DENY", "reason": "INVALID_INSTALL_REQUEST"}
        if selected_request["bindingId"] != self._binding["bindingId"]:
            return {"status": "DENY", "reason": "WRONG_AUTHORITY_BINDING"}
        if selected_request["expectedAuthorityEpoch"] is None:
            return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}
        ref = selected_request["snapshotRef"]
        try:
            relative = normalize_repo_path(ref["path"], label="authority snapshot")
        except LifecycleError:
            return {"status": "DENY", "reason": "INVALID_SNAPSHOT_REF"}
        try:
            root = Path(artifact_root).resolve()
            raw = read_authority_bytes(root / relative, max_bytes=1_048_576, root=root)
        except (LifecycleError, OSError, TypeError, ValueError) as exc:
            raise JournalUnavailable("Signed snapshot artifact is unavailable", write_outcome="NOT_STARTED") from exc
        if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            return {"status": "DENY", "reason": "SNAPSHOT_ARTIFACT_MISMATCH"}
        try:
            selected = load_json_object(raw, label="authority snapshot")
            validate_authority_snapshot_shape(selected)
        except (LifecycleError, TypeError, ValueError, RecursionError):
            return {"status": "DENY", "reason": "INVALID_SNAPSHOT_SHAPE"}
        with self._journal._transaction():
            self._require_binding(self._journal._db)
            return install_successor_snapshot(
                self._journal._db, self._binding, self._binding_digest,
                selected, selected_request["operationId"], selected_request["expectedAuthorityEpoch"],
                revocation_only=True,
            )
