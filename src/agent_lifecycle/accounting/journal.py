"""SQLite P01 journal for already-authorized controller effects.

This module neither authenticates a provider receipt nor dispatches a model.
Callers must establish policy, route, validity and source authority externally.
Only a proven empty pending opening inventory is supported by this core.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast as _validated_cast

from .closing_resource_recovery import closed_financial_totals
from .closing_resources import JournalRetentionMixin
from .contracts import (
    PROTECTED_STORAGE_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION,
    ClosureOutcome,
    EvidenceRef,
    JournalEvent,
    JournalHandle,
    UsageOutcome,
    canonical,
    digest,
    identity,
    uint,
)
from .contracts import _operation as _operation
from .normalization import JournalNormalizationMixin, UsageUnavailable
from .opening_balances import JournalAdmissionMixin, _legacy_open_identity_bindings, compile_opening
from .workflow_authority_store import _anchor_digest, _anchor_row_matches, _canonical_json_sha256
from .workflow_store import (
    BASE_STATEMENTS as BASE_STATEMENTS,
)
from .workflow_store import (
    P02_EVENTS,
    P02_TABLES,
    JournalStoreMixin,
    JournalUnavailable,
    RevisionConflict,
    _apply,
    _apply_delta_encoded,
    _BindingConflict,
    _event_payload,
    _local_identity,
    _WriteQueue,
)
from .workflow_store import (
    _apply_delta as _apply_delta,
)
from .workflow_store import (
    _Lease as _Lease,
)
from .workflow_store import (
    _state_delta as _state_delta,
)


class Journal(
    JournalHandle, JournalStoreMixin, JournalRetentionMixin, JournalAdmissionMixin, JournalNormalizationMixin
):
    _compile_opening = staticmethod(compile_opening)

    def __init__(
        self,
        path: str | Path,
        writer: EvidenceRef,
        *,
        fault_hook: Callable[[str], None] | None = None,
        storage_version: int = STORAGE_SCHEMA_VERSION,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(writer, EvidenceRef):
            raise ValueError("Trusted writer reference required")
        if storage_version not in (STORAGE_SCHEMA_VERSION, PROTECTED_STORAGE_SCHEMA_VERSION):
            raise ValueError("Unsupported explicit storage version")
        self.writer = writer
        # Runtime dependency, distinct from a caller's display/as-of timestamp.
        self._utc_clock = utc_clock if utc_clock is not None else lambda: datetime.now(UTC)
        self._storage_version = storage_version
        if str(path) == ":memory:":
            raise JournalUnavailable("Persistent local database required", write_outcome="NOT_STARTED")
        self._path = Path(path).resolve()
        self._owner = (os.getpid(), threading.get_ident())
        self._database_identity = None
        if self._path.exists():
            self._database_identity = _local_identity(self._path)
        self._queue = _WriteQueue(self._path)
        self._admission_depth = 0
        self.last_write_admission: dict = {}
        self._maintenance_deadline: float | None = None
        self._observation_scope: str | None = None
        self.fault_hook = fault_hook
        self._db = None
        try:
            with self._write_admission():
                if sys.version_info >= (3, 12):
                    self._db = sqlite3.connect(
                        str(self._path),
                        isolation_level=None,
                        timeout=1.0,
                        check_same_thread=True,
                        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
                    )
                else:
                    self._db = sqlite3.connect(
                        str(self._path),
                        isolation_level=None,
                        timeout=1.0,
                        check_same_thread=True,
                    )
                self._db.row_factory = sqlite3.Row
                self._schema_ready = False
                self._retention_scopes = frozenset()
                self._db.create_function("alk_retention_scope", 1, lambda scope: int(scope in self._retention_scopes))
                self._register_writer(self._db, self._storage_version)
                if self._storage_version == PROTECTED_STORAGE_SCHEMA_VERSION:
                    self._db.create_function("alk_anchor_digest", 1, _anchor_digest)
                    self._db.create_function("alk_anchor_row_matches", 12, _anchor_row_matches)
                    self._db.create_function("alk_canonical_json_sha256", 1, _canonical_json_sha256)
                    self._db.create_function("alk_stage_ack_verified", 0, lambda: 0)
                tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables:
                    if "schema_metadata" not in tables:
                        raise JournalUnavailable("Refusing an unrecognized existing database")
                    row = self._db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()
                    if row is None or row[0] != self._storage_version:
                        raise JournalUnavailable("Unknown schema version; no automatic migration")
                self._db.execute("PRAGMA journal_mode=DELETE")
                self._db.execute("PRAGMA synchronous=FULL")
                self._db.execute("PRAGMA foreign_keys=ON")
                self.configuration = {
                    key: self._db.execute("PRAGMA " + key).fetchone()[0]
                    for key in ("journal_mode", "synchronous", "foreign_keys")
                }
                if self.configuration != {"journal_mode": "delete", "synchronous": 2, "foreign_keys": 1}:
                    raise JournalUnavailable("Required SQLite configuration unavailable")
                if not tables:
                    self._create_schema()
                self._validate_schema(self._db, self._storage_version)
                self._schema_ready = True
                self._database_identity = _local_identity(self._path)
        except BaseException:
            if self._db is not None:
                self._db.close()
            raise

    def close(self) -> None:
        self._check_owner()
        self._db.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def _db(self):
        self._check_owner()
        return self._connection

    @_db.setter
    def _db(self, value):
        self._check_owner()
        self._connection = value

    def _check_owner(self) -> None:
        if self._owner != (os.getpid(), threading.get_ident()):
            raise JournalUnavailable("Inherited or cross-thread Journal cannot be used", write_outcome="NOT_STARTED")

    @contextmanager
    def _write_admission(self) -> Iterator[None]:
        self._check_owner()
        if self._admission_depth:
            yield  # Schema initialization reuses admission, not a SQLite transaction.
            return
        observation = {
            "status": "WAITING",
            "polls": 0,
            "ticket": None,
            "wait_seconds": 0.0,
            "transaction_outcome": "NOT_STARTED",
        }
        self.last_write_admission = observation
        timeout = 1.0
        if self._maintenance_deadline is not None:
            timeout = min(timeout, max(0.0, self._maintenance_deadline - time.monotonic()))
        try:
            with self._queue.slot(observation, timeout=timeout):
                if self._path.exists():
                    current = _local_identity(self._path)
                    if self._database_identity is not None and current != self._database_identity:
                        raise JournalUnavailable("Database identity changed", write_outcome="NOT_STARTED")
                    self._database_identity = current
                elif self._database_identity is not None:
                    raise JournalUnavailable("Database disappeared", write_outcome="NOT_STARTED")
                self._admission_depth = 1
                try:
                    yield
                finally:
                    self._admission_depth = 0
        except (OSError, JournalUnavailable) as exc:
            outcome = "NOT_STARTED" if observation["transaction_outcome"] == "NOT_STARTED" else "RECONCILE_REQUIRED"
            observation["transaction_outcome"] = outcome
            if isinstance(exc, JournalUnavailable):
                exc.write_outcome = outcome
                raise
            raise JournalUnavailable("Local write admission failed", write_outcome=outcome) from exc

    @contextmanager
    def _transaction(self, observation_scope: str | None = None) -> Iterator[None]:
        self._check_owner()
        if self._db.in_transaction:
            raise JournalUnavailable("Nested SQLite transaction refused", write_outcome="NOT_STARTED")
        with self._write_admission():
            previous_scope = self._observation_scope
            self._observation_scope = observation_scope
            started = False
            try:
                self._db.execute("BEGIN IMMEDIATE")
                started = True
                self.last_write_admission["transaction_outcome"] = "RECONCILE_REQUIRED"
                if self._schema_ready:
                    row = self._db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()
                    if row is None or row[0] != self._storage_version:
                        raise JournalUnavailable("Storage version changed; no automatic migration")
                yield
                if self.fault_hook:
                    self.fault_hook("before_commit")
                self._db.execute("COMMIT")
                if self.fault_hook:
                    self.fault_hook("after_commit")
                self.last_write_admission["transaction_outcome"] = "COMMITTED"
            except BaseException as exc:
                outcome = "RECONCILE_REQUIRED" if started or self._db.in_transaction else "NOT_STARTED"
                self.last_write_admission["transaction_outcome"] = outcome
                if self._db.in_transaction:
                    with suppress(sqlite3.Error):
                        self._db.execute("ROLLBACK")
                if isinstance(exc, sqlite3.Error):
                    raise JournalUnavailable(
                        "SQLite operation failed; reconcile before dispatch", write_outcome=outcome
                    ) from exc
                if isinstance(exc, JournalUnavailable):
                    exc.write_outcome = outcome
                raise
            finally:
                self._observation_scope = previous_scope

    def _load(self, scope: str) -> tuple[dict | None, int]:
        identity(scope)
        row = self._db.execute("SELECT data,revision FROM scope_state WHERE scope=?", (scope,)).fetchone()
        if row:
            return json.loads(row["data"]), row["revision"]
        if self._closed_scope(scope):
            return self._archive_state(scope)
        return None, 0

    def _key(self, kind: str, key: object, scope: str, owner: str, value: str) -> bool:
        """Reserve/check a global immutable key inside the current transaction."""
        encoded = canonical(key)
        if kind in {"source", "observed_final"}:
            self._check_observed(
                {"namespace": "final", "key": encoded, "scope": scope, "owner": owner, "digest": value}
            )
        row = self._db.execute("SELECT * FROM identities WHERE kind=? AND key=?", (kind, encoded)).fetchone()
        if row:
            if (row["scope"], row["owner"], row["digest"]) != (scope, owner, value):
                raise _BindingConflict("Conflicting " + kind, (scope, row["scope"]))
            return False
        for declared in self._db.execute(
            "SELECT i.value FROM archive_records a, json_each(a.payload,'$.protection.identities') i "
            "WHERE json_extract(i.value,'$[0]')=?",
            (kind,),
        ):
            if canonical(json.loads(declared[0])[1]) == encoded:
                raise JournalUnavailable("Missing archived identity projection; explicit rebuild required")
        self._db.execute("INSERT INTO identities VALUES(?,?,?,?,?)", (kind, encoded, scope, owner, value))
        return True

    def _record(self, scope: str, state: dict | None, revision: int, kind: str, payload: dict) -> int:
        next_revision = uint(revision + 1)
        encoded_payload = canonical(payload)
        event = JournalEvent(
            event_id=uuid.uuid4().hex,
            budget_scope_id=scope,
            transaction_id=uuid.uuid4().hex,
            journal_revision=next_revision,
            event_type=kind,
            payload=payload,
            payload_digest=hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest(),
            writer=self.writer,
            observed_at=datetime.now(UTC).isoformat(),
        )
        self._db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event.event_id,
                scope,
                next_revision,
                0,
                event.transaction_id,
                kind,
                encoded_payload,
                event.payload_digest,
                canonical(asdict(self.writer)),
                event.observed_at,
            ),
        )
        if self.fault_hook:
            self.fault_hook("after_event")
        if kind in P02_EVENTS and isinstance(payload, dict) and "state_delta" in payload and "after" not in payload:
            # Reuse only the encoding produced by this strict replay. No caller
            # can supply a prevalidated state or an unchecked serialized value.
            _, encoded_state = _apply_delta_encoded(state, payload["state_delta"])
        else:
            encoded_state = canonical(_apply(state, kind, payload, revision=revision))
        self._db.execute(
            (
                "INSERT INTO scope_state VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET "
                "revision=excluded.revision,data=excluded.data"
            ),
            (scope, next_revision, encoded_state),
        )
        if self.fault_hook:
            self.fault_hook("after_projection")
        return next_revision

    def _conflict(self, scopes: tuple[str, ...], reason: str, payload: dict) -> str:
        for scope in sorted(set(scopes)):
            if self._closed_scope(scope):
                self._append_exception(scope, payload, reason)
                continue
            state, revision = self._load(scope)
            if state is not None and state["gate"] != "CONFLICT":
                self._record(scope, state, revision, "CONFLICT", {"reason": reason, "evidence": payload})
        return "CONFLICT"

    def events(self, scope: str) -> list[dict]:
        return [
            dict(row)
            for row in self._db.execute("SELECT * FROM events WHERE scope=? ORDER BY revision,ordinal", (scope,))
        ]

    def bounded_prefix(
        self,
        scope: str,
        *,
        expected_revision: int,
        boundary: tuple[int, int],
        max_rows: int,
        max_bytes: int,
    ) -> dict:
        """Read a complete current prefix; size checks precede payload loading.

        This adds no event, schema or authority. Closed/compacted or incomplete
        histories cannot qualify as an empty initial preparation history.
        """
        identity(scope)
        uint(expected_revision)
        if (
            type(max_rows) is not int
            or not 1 <= max_rows <= 4096
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 16 * 1024 * 1024
            or type(boundary) is not tuple
            or len(boundary) != 2
            or any(type(v) is not int or v < 0 for v in boundary)
        ):
            raise ValueError("Invalid bounded prefix limits or boundary")
        with self._transaction(scope):
            row = self._db.execute(
                "SELECT revision FROM scope_state WHERE scope=?", (scope,)
            ).fetchone()
            if row is None:
                raise JournalUnavailable("Complete scope prefix unavailable")
            if row[0] != expected_revision:
                raise RevisionConflict("Prefix revision changed")
            metadata = self._db.execute(
                "SELECT revision,ordinal,"
                "length(CAST(payload AS BLOB))+length(CAST(writer AS BLOB))+"
                "length(CAST(event_id AS BLOB))+length(CAST(scope AS BLOB))+"
                "length(CAST(transaction_id AS BLOB))+length(CAST(kind AS BLOB))+"
                "length(CAST(digest AS BLOB))+"
                "length(CAST(observed_at AS BLOB)) AS bytes "
                "FROM events WHERE scope=? ORDER BY revision,ordinal LIMIT ?",
                (scope, max_rows + 1),
            ).fetchall()
            if (
                len(metadata) > max_rows
                or sum(item["bytes"] for item in metadata) > max_bytes
                or not metadata
                or len(metadata) != expected_revision
                or any(
                    item["revision"] != index or item["ordinal"] != 0
                    for index, item in enumerate(metadata, 1)
                )
                or boundary != (metadata[-1]["revision"], metadata[-1]["ordinal"])
            ):
                raise JournalUnavailable("Prefix incomplete or exceeds limits")
            events = [dict(item) for item in self._db.execute(
                "SELECT * FROM events WHERE scope=? ORDER BY revision,ordinal",
                (scope,),
            )]
            if any(
                hashlib.sha256(item["payload"].encode("utf-8")).hexdigest()
                != item["digest"]
                for item in events
            ):
                raise JournalUnavailable("Prefix payload integrity unavailable")
            body = {
                "schemaVersion": "agent-journal-bounded-prefix.v1",
                "scope": scope,
                "revision": expected_revision,
                "boundary": list(boundary),
                "complete": True,
                "rowCount": len(events),
                "utf8Bytes": sum(item["bytes"] for item in metadata),
                "events": events,
            }
            return {**body, "prefixDigest": digest(body)}

    def _source_preflight(self, receipt: dict) -> None:
        self._check_observed(
            {
                "namespace": "final",
                "key": canonical([receipt["source_id"], receipt["source_event_id"]]),
                "scope": receipt["budget_scope_id"],
                "owner": receipt["operation_id"],
                "digest": digest(receipt),
                "raw_digest": receipt["raw_evidence"]["digest"],
            }
        )

    def _preflight_supplied_finals(self, scope: str, receipts: list[dict]) -> None:
        seen: dict[str, str] = {}
        affected, problems = {scope}, []
        for receipt in receipts:
            affected.add(receipt["budget_scope_id"])
            try:
                self._source_preflight(receipt)
            except _BindingConflict as exc:
                affected.update(exc.scopes)
                problems.append(str(exc))
            key = canonical([receipt["source_id"], receipt["source_event_id"]])
            checksum = digest(receipt)
            if key in seen and seen[key] != checksum:
                problems.append("Final identity repeated with another binding inside batch")
            seen[key] = checksum
            if receipt["budget_scope_id"] != scope:
                problems.append("Final belongs to another requested scope")
        if problems:
            raise _BindingConflict("; ".join(sorted(set(problems))), tuple(sorted(affected)))

    def _v2_unavailable(
        self,
        scope: str,
        state: dict,
        revision: int,
        reason: str,
        evidence: dict,
        *,
        overflow: bool = False,
        reason_kind: str = "SOURCE_OBSERVATION",
    ) -> UsageOutcome:
        after = copy.deepcopy(state)
        receipts = evidence.get("receipts", [])
        if "receipt_id" in evidence:
            receipts = [evidence]

        def bound_pending(value):
            op = state.get("operations", {}).get(value.get("operation_id"))
            if not op or not op["claim_id"] or op["state"] not in {"RESERVED", "DISPATCHED", "UNAVAILABLE"}:
                return False
            binding = op["binding"]
            fields = (
                "budget_scope_id",
                "operation_id",
                "dispatch_key",
                "permit_id",
                "attempt_id",
                "route_id",
                "source_id",
                "unit_definition_id",
            )
            return (
                value.get("binding_digest") == op["digest"]
                and all(value.get(k) == binding[k] for k in fields)
                and any(
                    p["source_id"] == value.get("source_id")
                    and p["schema_version"] == value.get("source_schema_version")
                    and p["unit_definition_id"] == value.get("unit_definition_id")
                    and p["qualification_ref"] == value.get("attestation")
                    for p in state.get("profiles", {}).values()
                )
            )

        operation_only = (
            reason_kind == "OPERATION_PENDING" and bool(receipts) and all(bound_pending(r) for r in receipts)
        )
        if not operation_only and reason_kind == "OPERATION_PENDING":
            reason_kind = "SOURCE_OBSERVATION"
        if overflow:
            reason_kind = "OVERFLOW"
            operation_only = False
        reasons = after.setdefault("unresolved_reasons", {})
        affected = {r["operation_id"] for r in receipts}
        affected.update(a["operation_id"] for a in evidence.get("atoms", []))
        if operation_only:
            for owner in affected:
                reasons["pending:" + owner] = {
                    "kind": "OPERATION_PENDING",
                    "operation_id": owner,
                    "evidence_digest": digest(evidence),
                }
        else:
            key = "global:" + digest([reason_kind, evidence])
            reasons[key] = {
                "kind": reason_kind,
                "source_profile": evidence.get("profile_id"),
                "epoch": evidence.get("epoch"),
                "source_event_id": evidence.get("source_event_id"),
                "evidence_digest": digest(evidence),
                "detail": reason,
            }
            after["qualified"] = False
        for owner in affected:
            op = after.get("operations", {}).get(owner)
            if op and op["claim_id"] is not None and op["state"] in {"RESERVED", "DISPATCHED", "UNAVAILABLE"}:
                op["state"] = "UNAVAILABLE"
        after["input_unavailable"] = True
        if after["gate"] not in {"CONFLICT", "CLOSED", "BOUND_BROKEN"}:
            after["gate"] = "BOUND_BROKEN" if overflow else "INCOMPLETE"
        entries = []
        profile = state.get("profiles", {}).get(evidence.get("profile_id"))
        if profile and "source_event_id" in evidence and "raw_evidence" in evidence:
            binding = {
                "observation_digest": digest(evidence),
                "raw_digest": evidence["raw_evidence"]["digest"],
                "finals": {
                    r["operation_id"]: digest(r)
                    for r in receipts
                    if r["source_event_id"] == evidence["source_event_id"]
                },
                "input": evidence,
            }
            entries.append(
                self._entry(
                    "source_observations",
                    [profile["source_id"], evidence["source_event_id"]],
                    scope,
                    "observation",
                    binding,
                )
            )
        keys = [
            ["observed_final", [r["source_id"], r["source_event_id"]], scope, r["operation_id"], digest(r)]
            for r in receipts
        ]
        self._db.execute("SAVEPOINT unavailable_batch")
        try:
            self._preflight_supplied_finals(scope, receipts)
            revision = self._commit_v2(
                scope,
                state,
                revision,
                "INPUT_UNAVAILABLE",
                after,
                entries,
                keys,
                {"reason": reason, "reason_kind": reason_kind, "input": evidence},
            )
            self._db.execute("RELEASE unavailable_batch")
            return UsageOutcome("UNAVAILABLE", revision, reason)
        except _BindingConflict as exc:
            self._db.execute("ROLLBACK TO unavailable_batch")
            self._db.execute("RELEASE unavailable_batch")
            self._conflict(exc.scopes, str(exc), evidence)
            return UsageOutcome("CONFLICT", self._load(scope)[1], str(exc))

    def _import_entries(self, scope: str, after: dict) -> tuple[list, list]:
        entries, keys = [], []
        value = after["opening_import"]
        keys.append(
            [
                "opening",
                [scope, value["opening"]["opening_balance_id"]],
                scope,
                value["opening"]["opening_balance_id"],
                after["opening_import_digest"],
            ]
        )
        for source, event in value["opening"]["covered_source_events"]:
            keys.append(
                [
                    "source",
                    [source, event],
                    scope,
                    "opening:" + value["opening"]["opening_balance_id"],
                    after["opening_import_digest"],
                ]
            )
        for name, profile in after["profiles"].items():
            entries.append(self._entry("source_profiles", [scope, name], scope, name, profile))
        for operation_id, op in after["operations"].items():
            binding = op["binding"]
            for kind, key in (
                ("operation", [scope, operation_id]),
                ("dispatch", [scope, binding["dispatch_key"]]),
                ("permit", binding["permit_id"]),
            ):
                keys.append([kind, key, scope, operation_id, op["digest"]])
            if op["claim_id"] is not None:
                keys.append(["claim", binding["permit_id"], scope, operation_id, digest(op["claim_id"])])
        for operation_id, final in after["accepted_finals"].items():
            receipt = final["receipt"]
            self._source_preflight(receipt)
            checksum = digest(receipt)
            keys.extend(
                [
                    ["source", [receipt["source_id"], receipt["source_event_id"]], scope, operation_id, checksum],
                    ["settlement", [scope, operation_id], scope, operation_id, checksum],
                ]
            )
            for atom in final["semantics"]["atoms"]:
                entries.append(
                    self._entry(
                        "coverage_atoms", [atom["namespace"], atom["epoch"], atom["atom_id"]], scope, operation_id, atom
                    )
                )
        return entries, keys

    def import_opening(self, scope, policy, opening_import, *, expected_revision=0) -> UsageOutcome:
        uint(expected_revision)
        # Compilation is repeated under the write lock; external candidates are not accepted.
        with self._transaction(scope.budget_scope_id):
            if self._retained("run_closures", scope.run_id):
                value = json.loads(canonical(asdict(opening_import)))
                target = (
                    scope.budget_scope_id
                    if self._closed_scope(scope.budget_scope_id)
                    else _validated_cast(dict, self.closed_run(scope.run_id))["closure"]["scope_revisions"][0][0]
                )
                if self._observed_candidates(target, value):
                    self._closed_evidence(target, value)
                return UsageOutcome("CLOSED", _validated_cast(sqlite3.Row, self._closed_scope(target))["revision"])
            existing, revision = self._load(scope.budget_scope_id)
            value = json.loads(canonical(asdict(opening_import)))
            if existing is not None:
                if (
                    (existing.get("opening_import") == value or existing.get("opening_import_digest") == digest(value))
                    and existing["scope"] == json.loads(canonical(asdict(scope)))
                    and existing["policy"] == json.loads(canonical(asdict(policy)))
                ):
                    return UsageOutcome("ALREADY_IMPORTED", revision)
                return UsageOutcome(
                    self._conflict((scope.budget_scope_id,), "Incompatible opening import", value), revision + 1
                )
            if expected_revision != revision:
                raise RevisionConflict("Stale import revision")
            try:
                after = compile_opening(scope, policy, opening_import)
            except UsageUnavailable as exc:
                # No admission is possible without a scope. Preserve the rejected input
                # in an incomplete legacy shell plus immutable INPUT_UNAVAILABLE event.
                data = {"scope": asdict(scope), "policy": asdict(policy), "opening": asdict(opening_import.opening)}
                data = json.loads(canonical(data))
                data["opening"]["pending_operations"] = None
                revision = self._record(scope.budget_scope_id, None, 0, "OPEN", data)
                existing, _ = self._load(scope.budget_scope_id)
                return self._v2_unavailable(
                    scope.budget_scope_id, _validated_cast(dict, existing), revision, str(exc), value
                )
            self._db.execute("SAVEPOINT v2_import")
            try:
                entries, keys = self._import_entries(scope.budget_scope_id, after)
                revision = self._commit_v2(
                    scope.budget_scope_id, None, 0, "IMPORT_OPENING", after, entries, keys, value
                )
                self._db.execute("RELEASE v2_import")
                return UsageOutcome("IMPORTED", revision)
            except _BindingConflict as exc:
                self._db.execute("ROLLBACK TO v2_import")
                self._db.execute("RELEASE v2_import")
                # Preserve the candidate evidence, but none of its balances/keys can
                # be accepted. Existing owners are quarantined in this transaction.
                blocked = copy.deepcopy(after)
                blocked["qualified"] = False
                blocked["gate"] = "CONFLICT"
                blocked["operations"] = {}
                blocked["accepted_finals"] = {}
                blocked["baselines"] = {}
                revision = self._commit_v2(scope.budget_scope_id, None, 0, "INPUT_UNAVAILABLE", blocked, [], [], value)
                self._conflict(exc.scopes, str(exc), value)
                return UsageOutcome("CONFLICT", self._load(scope.budget_scope_id)[1])

    @staticmethod
    def _financial_totals(state: dict, revision: int) -> dict:
        return closed_financial_totals(state, revision)

    def _live_facts(self, scope: str, *, restore: bool = False) -> tuple[dict, int, list, list]:
        """Pure per-scope replay; closure must not repair its own admission evidence."""
        state: dict | None = None
        revision = 0
        indexes: dict[tuple[str, str], dict] = {}
        identities: dict[tuple[str, str], list] = {}
        for row in self._db.execute("SELECT * FROM events WHERE scope=? ORDER BY revision,ordinal", (scope,)):
            self._checkpoint("archive_replay")
            revision += 1
            payload = _event_payload(row, revision)
            declarations = []
            if row["kind"] in P02_EVENTS:
                for entry in payload.get("indexes", []):
                    if entry["scope"] != scope or entry["table"] not in P02_TABLES:
                        raise JournalUnavailable("Invalid declared scope index")
                    key = (entry["table"], entry["key"])
                    if key in indexes and canonical(indexes[key]) != canonical(entry):
                        raise JournalUnavailable("Conflicting declared immutable index")
                    indexes[key] = entry
                declarations = payload.get("identities", [])
            elif row["kind"] == "OPEN":
                declarations = _legacy_open_identity_bindings(self._db, scope, revision, payload, state)
            elif row["kind"] == "RESERVE":
                op = payload["operation"]
                declarations = [
                    [kind, key, scope, op["operation_id"], digest(op)]
                    for kind, key in (
                        ("operation", [scope, op["operation_id"]]),
                        ("dispatch", [scope, op["dispatch_key"]]),
                        ("permit", op["permit_id"]),
                    )
                ]
            elif row["kind"] == "CLAIM":
                op = _validated_cast(dict, state)["operations"][payload["operation_id"]]
                declarations = [
                    ["claim", op["binding"]["permit_id"], scope, payload["operation_id"], digest(payload["claim_id"])]
                ]
            elif row["kind"] in ("SETTLE", "OVERFLOW"):
                receipt = payload["receipt"]
                declarations = [
                    [kind, key, scope, receipt["operation_id"], digest(receipt)]
                    for kind, key in (
                        ("settlement", [scope, receipt["operation_id"]]),
                        ("source", [receipt["source_id"], receipt["source_event_id"]]),
                    )
                ]
            for declaration in declarations:
                kind, key, owned_scope, owner, checksum = declaration
                key = (kind, canonical(key))
                if owned_scope != scope or (key in identities and identities[key] != declaration):
                    raise JournalUnavailable("Conflicting declared identity")
                identities[key] = declaration
            state = _apply(state, row["kind"], payload, revision=row["revision"] - 1)
        if state is None:
            raise JournalUnavailable("Closed scope has no financial replay root")
        for entry in indexes.values():
            table = entry["table"]
            row = self._db.execute(f"SELECT * FROM {table} WHERE key=?", (entry["key"],)).fetchone()
            expected = (entry["key"], scope, entry["owner"], digest(entry["payload"]), canonical(entry["payload"]))
            if row is None and restore:
                self._db.execute(f"INSERT INTO {table} VALUES(?,?,?,?,?)", expected)
            elif row is None or tuple(row) != expected:
                raise JournalUnavailable("Live immutable index missing or changed")
        for kind, key, owned_scope, owner, checksum in identities.values():
            encoded = canonical(key)
            row = self._db.execute("SELECT * FROM identities WHERE kind=? AND key=?", (kind, encoded)).fetchone()
            expected = (kind, encoded, owned_scope, owner, checksum)
            if row is None and restore:
                self._db.execute("INSERT INTO identities VALUES(?,?,?,?,?)", expected)
            elif row is None or tuple(row) != expected:
                raise JournalUnavailable("Live immutable identity missing or changed")
        for table in P02_TABLES:
            actual = {r[0] for r in self._db.execute(f"SELECT key FROM {table} WHERE scope=?", (scope,))}
            if actual != {key for (name, key) in indexes if name == table}:
                raise JournalUnavailable("Extra live immutable index")
        actual = {(r[0], r[1]) for r in self._db.execute("SELECT kind,key FROM identities WHERE scope=?", (scope,))}
        if actual != set(identities):
            raise JournalUnavailable("Extra live financial identity")
        return state, revision, list(indexes.values()), list(identities.values())

    @staticmethod
    def _closure_outcome(value: dict, status: str) -> ClosureOutcome:
        c = value["closure"]
        return ClosureOutcome(
            status,
            c["run_id"],
            c["closure_id"],
            value["summary_digest"],
            tuple((s, r + 1) for s, r in c["scope_revisions"]),
            value["eligible_after"],
        )

    def _index(self, table: str, key: str, scope: str, owner: str, payload: dict) -> dict:
        if table not in P02_TABLES:
            raise ValueError("Unknown immutable index")
        encoded, checksum = canonical(payload), digest(payload)
        if table == "source_observations":
            self._check_observed(
                {
                    "namespace": "raw",
                    "key": key,
                    "scope": scope,
                    "owner": owner,
                    "digest": payload["observation_digest"],
                    "raw_digest": payload["raw_digest"],
                    "finals": payload.get("finals", {}),
                }
            )
        row = self._db.execute(f"SELECT * FROM {table} WHERE key=?", (key,)).fetchone()
        if row:
            if (row["scope"], row["owner"], row["digest"], row["payload"]) != (scope, owner, checksum, encoded):
                raise _BindingConflict("Conflicting " + table, (scope, row["scope"]))
        else:
            if (
                table in ("coverage_atoms", "corroborating_finals")
                and self._db.execute(
                    "SELECT a.key FROM archive_records a, json_each(a.payload,'$.protection.indexes') i "
                    "WHERE json_extract(i.value,'$.table')=? AND json_extract(i.value,'$.key')=? LIMIT 1",
                    (table, key),
                ).fetchone()
            ):
                raise JournalUnavailable("Missing archived financial index projection; explicit rebuild required")
            self._db.execute(f"INSERT INTO {table} VALUES(?,?,?,?,?)", (key, scope, owner, checksum, encoded))
        return {"table": table, "key": key, "scope": scope, "owner": owner, "payload": payload}
