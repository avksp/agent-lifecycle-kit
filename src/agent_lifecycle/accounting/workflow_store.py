"""Shared SQLite journal storage and migration methods.

This module neither authenticates a provider receipt nor dispatches a model.
Callers must establish policy, route, validity and source authority externally.
Only a proven empty pending opening inventory is supported by this core.
"""

from __future__ import annotations

import copy
import errno
import json
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from typing import cast as _validated_cast

from .closing_resource_policy import _apply_closing_policy
from .contracts import (
    PROTECTED_STORAGE_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION,
    EvidenceRef,
    _JournalStoragePort,
    _local_identity,
    _refresh_v2,
    canonical,
    digest,
)
from .contracts import RevisionConflict as RevisionConflict
from .contracts import _BindingConflict as _BindingConflict
from .contracts import _operation as _operation
from .contracts import _projection as _projection
from .workflow_authority_store import (
    AUTHORITY_TABLES,
    _anchor_digest,
    _anchor_row_matches,
    _canonical_json_sha256,
    _financial_snapshot_digest,
    _retarget_v4_writer_guards,
    _retarget_workflow_guards,
    _storage_schema_digest,
    _validate_v6_storage_receipt,
    create_v6_workflow_extension,
)
from .workflow_state_store import (
    WORKFLOW_TABLES,
    JournalUnavailable,
    _apply_delta,
    _state_delta,
    create_workflow_schema,
)
from .workflow_state_store import _apply_delta_encoded as _apply_delta_encoded


def _initial(payload: dict) -> dict:
    opening, policy = payload["opening"], payload["policy"]
    qualified = (
        opening["run_overhead"] is not None
        and all(x is not None for x in opening["task_spent"].values())
        and opening["pending_operations"] == []
    )
    return {
        "scope": payload["scope"],
        "policy": policy,
        "opening": opening,
        "operations": {},
        "task_spent": dict(opening["task_spent"]),
        "overhead": opening["run_overhead"],
        "protected": dict(policy["protected_closeout"]),
        "qualified": qualified,
        "gate": "READY" if qualified else "INCOMPLETE",
    }


def _apply(state: dict | None, kind: str, payload: dict, *, revision: int | None = None) -> dict:
    """Pure replay of persisted, validated effects; never call host during replay."""
    if kind in P02_EVENTS:
        if not isinstance(payload, dict) or ("after" in payload) == ("state_delta" in payload):
            raise JournalUnavailable("Expected exactly one P02 state representation")
        if "state_delta" in payload:
            return _apply_delta(state, payload["state_delta"])
        # Historical v2 bytes remain readable only via explicit storage migration.
        if not isinstance(payload["after"], dict):
            raise JournalUnavailable("Malformed legacy P02 state")
        try:
            canonical(payload["after"])
        except (TypeError, ValueError, RecursionError) as exc:
            raise JournalUnavailable("Invalid legacy P02 state") from exc
        return copy.deepcopy(payload["after"])
    if kind == "OPEN":
        return _initial(payload)
    assert state is not None
    if kind == "CLOSING_POLICY_APPLIED":
        return _apply_closing_policy(state, payload, revision)
    if kind == "CONFLICT":
        state["qualified"] = False
        state["gate"] = "CONFLICT"
        return state
    if kind == "RESERVE":
        op = payload["operation"]
        state["operations"][op["operation_id"]] = {
            "binding": op,
            "digest": digest(op),
            "state": "RESERVED",
            "claim_id": None,
            "reservation": op["upper_bound_tokens"],
            "actual": None,
        }
        if op["operation_class"] == "CLOSEOUT":
            state["protected"][op["closeout_allocation_id"]] -= op["upper_bound_tokens"]
        return state
    op = state["operations"][payload["operation_id"]]
    if kind == "CLAIM":
        op["claim_id"] = payload["claim_id"]
    elif kind == "DISPATCH":
        op["state"] = "DISPATCHED"
    elif kind == "UNAVAILABLE":
        op["state"] = "UNAVAILABLE"
        if state.get("mode") == "COVERAGE_V2":
            state.setdefault("unresolved_reasons", {})["pending:" + payload["operation_id"]] = {
                "kind": "OPERATION_PENDING",
                "operation_id": payload["operation_id"],
            }
        # Uncertainty about this operation must not erase an earlier blocker.
        # Only ordinary INCOMPLETE can clear when pending evidence resolves.
        if state["gate"] not in {"BOUND_BROKEN", "CONFLICT", "CLOSED"}:
            state["gate"] = "INCOMPLETE"
    elif kind == "OVERFLOW":
        state["qualified"] = False
        if state["gate"] not in {"CONFLICT", "CLOSED"}:
            state["gate"] = "BOUND_BROKEN"
        op["state"] = "UNAVAILABLE"
    elif kind in {"SETTLE", "CANCEL"}:
        amount = payload["receipt"]["reported_tokens"] if kind == "SETTLE" else 0
        binding = op["binding"]
        if kind == "SETTLE":
            task = binding["task_id"]
            if task is None:
                if state["overhead"] is None:
                    state.setdefault("known_partials", {})[""] = state.get("known_partials", {}).get("", 0) + amount
                else:
                    state["overhead"] += amount
            else:
                if state["task_spent"][task] is None:
                    state.setdefault("known_partials", {})[task] = state.get("known_partials", {}).get(task, 0) + amount
                else:
                    state["task_spent"][task] += amount
            op["actual"] = amount
            op["state"] = "SETTLED"
        else:
            op["state"] = "CANCELLED_WITH_NO_DISPATCH_PROOF"
        if (
            binding["operation_class"] == "CLOSEOUT"
            and state["protected"].get(binding["closeout_allocation_id"]) is not None
        ):
            state["protected"][binding["closeout_allocation_id"]] += max(binding["upper_bound_tokens"] - amount, 0)
        op["reservation"] = 0
        if amount > binding["upper_bound_tokens"]:
            if state["gate"] not in {"CONFLICT", "CLOSED"}:
                state["gate"] = "BOUND_BROKEN"
        elif (
            state["qualified"]
            and state["gate"] == "INCOMPLETE"
            and not any(x["state"] == "UNAVAILABLE" for x in state["operations"].values())
        ):
            state["gate"] = "READY"
            if state.get("mode") == "COVERAGE_V2":
                state["input_unavailable"] = False
    else:
        raise JournalUnavailable("Unknown journal event")
    return _refresh_v2(state)


BASE_STATEMENTS = [
    "CREATE TABLE schema_metadata(singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)",
    (
        "CREATE TABLE scope_state(scope TEXT PRIMARY KEY NOT NULL, revision INTEGER NOT NULL "
        "CHECK(typeof(revision)='integer' AND revision>=0), data TEXT NOT NULL)"
    ),
    (
        "CREATE TABLE events(event_id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, revision "
        "INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), ordinal INTEGER NOT "
        "NULL CHECK(ordinal=0), transaction_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, payload "
        "TEXT NOT NULL, digest TEXT NOT NULL, writer TEXT NOT NULL, observed_at TEXT NOT NULL, "
        "UNIQUE(scope,revision,ordinal))"
    ),
    (
        "CREATE TABLE identities(kind TEXT NOT NULL, key TEXT NOT NULL, scope TEXT NOT NULL, "
        "owner TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(kind,key))"
    ),
]
P02_TABLES = ("input_evidence", "source_profiles", "coverage_atoms", "source_observations", "corroborating_finals")
P02_EVENTS = frozenset(
    {
        "PROFILE_REGISTERED",
        "IMPORT_OPENING",
        "NORMALIZED_BATCH",
        "FINAL_CORROBORATED",
        "OBSERVATION_RECORDED",
        "IMPORT_EVIDENCE_COMPLETED",
        "INPUT_UNAVAILABLE",
        "RUN_CLOSED",
    }
)

RETENTION_TABLES = (
    "run_closures",
    "archive_records",
    "archive_observation_keys",
    "financial_exceptions",
    "exception_identity_keys",
    "cleanup_receipts",
    "maintenance_receipts",
)
DETAIL_TABLES = (
    "events",
    "input_evidence",
    "source_observations",
    "source_profiles",
    "source_baselines",
    "scope_state",
)


def _event_payload(row: sqlite3.Row, revision: int) -> dict:
    try:
        payload = json.loads(row["payload"])
        if (
            row["revision"] != revision
            or row["ordinal"] != 0
            or not isinstance(payload, dict)
            or digest(payload) != row["digest"]
        ):
            raise JournalUnavailable("Journal ordering or digest mismatch")
        return payload
    except (TypeError, ValueError, RecursionError) as exc:
        raise JournalUnavailable("Invalid event encoding") from exc


# Scheduling leases contain no financial data. SQLite remains the authority.
_LEASE_FDS: set[int] = set()
_LEASE_MUTEX = threading.RLock()


def _fork_child_leases() -> None:
    # Never unlock a shared open-file description: that would unlock the parent.
    try:
        for fd in _LEASE_FDS:
            with suppress(OSError):
                os.close(fd)
    finally:
        _LEASE_FDS.clear()
        _LEASE_MUTEX.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_LEASE_MUTEX.acquire, after_in_parent=_LEASE_MUTEX.release, after_in_child=_fork_child_leases
    )


if TYPE_CHECKING:

    class _WindowsFileLock(Protocol):
        LK_NBLCK: int

        def locking(self, fd: int, mode: int, nbytes: int) -> None: ...


class _Lease:
    def __init__(self, path: Path, flags: int = 0) -> None:
        self.pid = os.getpid()
        self.path = path
        with _LEASE_MUTEX:
            try:
                _local_identity(path)  # lstat also sees dangling links, before open/create.
            except FileNotFoundError:
                if not flags & os.O_CREAT:
                    raise
            self.fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | flags, 0o600)
            _LEASE_FDS.add(self.fd)
        try:
            value = os.fstat(self.fd)
            self.identity = value.st_dev, value.st_ino
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or self.identity != _local_identity(path):
                raise JournalUnavailable("Write-admission lease identity changed", write_outcome="NOT_STARTED")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.pid != os.getpid():
            return
        with _LEASE_MUTEX:
            if self.fd in _LEASE_FDS:
                _LEASE_FDS.remove(self.fd)
                os.close(self.fd)

    def try_lock(self) -> bool:
        if self.pid != os.getpid():
            raise JournalUnavailable("Inherited lease cannot be used", write_outcome="NOT_STARTED")
        try:
            if os.name == "posix" and hasattr(os, "register_at_fork"):
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif os.name == "nt":
                import msvcrt

                os.lseek(self.fd, 0, os.SEEK_SET)
                windows_lock = _validated_cast("_WindowsFileLock", msvcrt)
                windows_lock.locking(self.fd, windows_lock.LK_NBLCK, 1)
            else:
                raise JournalUnavailable("Local lease platform unsupported", write_outcome="NOT_STARTED")
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise


class _WriteQueue:
    """FIFO after registration, for cooperating writers on one local DB path."""

    def __init__(self, path: Path) -> None:
        self.directory = path.with_name(path.name + ".alk-writers")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.identity = _local_identity(self.directory, directory=True)

    @staticmethod
    def _pause(deadline: float, observation: dict) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise JournalUnavailable("Write admission deadline expired", write_outcome="NOT_STARTED")
        observation["polls"] += 1
        time.sleep(min(0.002, remaining))

    @contextmanager
    def _guard(self, deadline: float, observation: dict) -> Iterator[None]:
        if _local_identity(self.directory, directory=True) != self.identity:
            raise JournalUnavailable("Write queue directory changed", write_outcome="NOT_STARTED")
        lease = _Lease(self.directory / "guard", os.O_CREAT)
        try:
            while True:
                if time.monotonic() >= deadline:
                    raise JournalUnavailable("Write admission deadline expired", write_outcome="NOT_STARTED")
                if lease.try_lock():
                    if _local_identity(lease.path) != lease.identity:
                        raise JournalUnavailable("Write queue guard changed", write_outcome="NOT_STARTED")
                    yield
                    break
                self._pause(deadline, observation)
        finally:
            lease.close()

    def _live(self) -> list[str]:
        entries: list[Path] = []
        for path in self.directory.iterdir():
            if path.name == "guard":
                continue
            if len(entries) >= 64 or re.fullmatch(r"[0-9]{20}-[0-9a-f]{32}", path.name) is None:
                raise JournalUnavailable("Write queue inventory unsupported", write_outcome="NOT_STARTED")
            entries.append(path)
        live = []
        for path in sorted(entries):
            lease = _Lease(path)
            try:
                stale = lease.try_lock()
            finally:
                lease.close()
            if stale:
                path.unlink()  # Guard excludes registration/scanning; no PID guessing.
            else:
                live.append(path.name)
        return live

    @contextmanager
    def slot(self, observation: dict, *, timeout: float = 1.0) -> Iterator[None]:
        start = time.monotonic()
        deadline = start + timeout
        lease = None
        try:
            with self._guard(deadline, observation):
                live = self._live()
                if len(live) >= 64:
                    raise JournalUnavailable("Write queue full", write_outcome="NOT_STARTED")
                ticket = int(live[-1][:20]) + 1 if live else 0
                if ticket >= 10**20:
                    raise JournalUnavailable("Write queue ticket exhausted", write_outcome="NOT_STARTED")
                name = f"{ticket:020d}-{uuid.uuid4().hex}"
                lease = _Lease(self.directory / name, os.O_CREAT | os.O_EXCL)
                if not lease.try_lock():
                    raise JournalUnavailable("New write lease unavailable", write_outcome="NOT_STARTED")
                observation.update(ticket=name, predecessors=len(live))
                first = not live
            while not first:
                self._pause(deadline, observation)
                with self._guard(deadline, observation):
                    live = self._live()
                    if name not in live:
                        raise JournalUnavailable("Live write lease disappeared", write_outcome="NOT_STARTED")
                    first = live[0] == name
            if time.monotonic() >= deadline:
                raise JournalUnavailable("Write admission deadline expired", write_outcome="NOT_STARTED")
            observation.update(status="ADMITTED", wait_seconds=time.monotonic() - start)
            yield
        finally:
            if observation["status"] == "WAITING":
                observation.update(status="REFUSED", wait_seconds=time.monotonic() - start)
            if lease is not None and lease.pid == os.getpid():
                lease.close()  # End the lease even when cleanup cannot get guard.
                try:
                    with self._guard(time.monotonic() + 0.05, observation):
                        if lease.path.exists():
                            if _local_identity(lease.path) != lease.identity:
                                raise JournalUnavailable("Write queue cleanup identity changed")
                            lease.path.unlink()
                    observation["cleanup"] = "DONE"
                except JournalUnavailable as exc:
                    if str(exc) != "Write admission deadline expired":
                        raise
                    observation["cleanup"] = "DEFERRED_STALE_LEASE"


class JournalStoreMixin(_JournalStoragePort):
    def _create_schema(self) -> None:
        version = getattr(self, "_storage_version", STORAGE_SCHEMA_VERSION)
        with self._transaction():
            for statement in BASE_STATEMENTS:
                self._db.execute(statement)
            self._db.execute("INSERT INTO schema_metadata VALUES(1,?)", (version,))
            for table in ("events", "identities"):
                for action in ("UPDATE", "DELETE"):
                    self._db.execute(
                        f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable journal record'); END"
                    )
            self._create_v2_schema()
            self._create_writer_guard(self._db, version)
            self._create_v4_schema(self._db, writer_version=version)
            create_workflow_schema(self._db, writer_version=version)
            if version == PROTECTED_STORAGE_SCHEMA_VERSION:
                self._db.execute(
                    "INSERT INTO workflow_storage_migrations VALUES(1,'init-v6',NULL,6,NULL,?,?,?)",
                    (
                        _storage_schema_digest(self._db),
                        _financial_snapshot_digest(self._db),
                        digest(asdict(self.writer)),
                    ),
                )

    def _create_v2_schema(self) -> None:
        for table in P02_TABLES:
            self._db.execute(
                f"CREATE TABLE {table}(key TEXT PRIMARY KEY NOT NULL, scope "
                "TEXT NOT NULL, owner TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            for action in ("UPDATE", "DELETE"):
                self._db.execute(
                    f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'immutable journal record'); END"
                )
        self._db.execute(
            "CREATE TABLE source_baselines(scope TEXT NOT NULL, key TEXT NOT NULL, revision "
            "INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(scope,key))"
        )

    @staticmethod
    def _register_writer(db: sqlite3.Connection, version: int = STORAGE_SCHEMA_VERSION) -> None:
        db.create_function("alk_storage_writer_version", 0, lambda: version)

    @staticmethod
    def _create_writer_guard(db: sqlite3.Connection, version: int = STORAGE_SCHEMA_VERSION) -> None:
        # The function is connection-local: an already-open v2 client lacks it.
        # This fences old journal writers, not malicious arbitrary SQL clients.
        db.execute(
            "CREATE TRIGGER require_storage_writer BEFORE INSERT ON events BEGIN "
            f"SELECT CASE WHEN alk_storage_writer_version() IS NOT {version} "
            f"OR (SELECT version FROM schema_metadata WHERE singleton=1) IS NOT {version} "
            "THEN RAISE(ABORT,'incompatible storage writer') END; END"
        )

    @classmethod
    def _validate_schema(cls, db: sqlite3.Connection, version: int) -> None:
        # Compare actual SQL, columns and immutable triggers to a local canonical
        # schema. This creates only an in-memory template, not an automatic migration.
        if version not in (1, 2, 3, 4, 5, PROTECTED_STORAGE_SCHEMA_VERSION):
            raise JournalUnavailable("Unknown storage schema")
        with sqlite3.connect(":memory:") as template:
            for statement in BASE_STATEMENTS:
                template.execute(statement)
            for table in ("events", "identities"):
                for action in ("UPDATE", "DELETE"):
                    template.execute(
                        f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable journal record'); END"
                    )
            if version >= 2:
                dummy = object.__new__(cls)
                dummy._owner = (os.getpid(), threading.get_ident())
                dummy._db = template
                dummy._create_v2_schema()
            if version >= 3:
                cls._create_writer_guard(template, version)
            if version >= 4:
                cls._create_v4_schema(template, writer_version=version)
            if version >= 5:
                create_workflow_schema(template, writer_version=version)

            def definition(connection):
                return {
                    (r[0], r[1]): r[2]
                    for r in connection.execute(
                        "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','trigger')"
                    )
                }

            if definition(db) != definition(template):
                raise JournalUnavailable("Partial, altered or unknown storage schema")
            if version == PROTECTED_STORAGE_SCHEMA_VERSION:
                _validate_v6_storage_receipt(db)

    @classmethod
    def _migrate_v5_storage_fixture(cls, path: str | Path, writer: EvidenceRef, *, fault_hook=None) -> str:
        """Exercise atomic storage migration locally; this grants no operator or workflow authority."""
        if not isinstance(writer, EvidenceRef) or not Path(path).is_file():
            raise JournalUnavailable("Explicit existing v5 database and writer required")
        source = Path(path)
        before_identity = _local_identity(source)
        db = sqlite3.connect(str(source), isolation_level=None, timeout=1)
        db.row_factory = sqlite3.Row
        cls._register_writer(db, PROTECTED_STORAGE_SCHEMA_VERSION)
        db.create_function("alk_anchor_digest", 1, _anchor_digest)
        db.create_function("alk_anchor_row_matches", 12, _anchor_row_matches)
        db.create_function("alk_canonical_json_sha256", 1, _canonical_json_sha256)
        db.create_function("alk_stage_ack_verified", 0, lambda: 0)
        try:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise JournalUnavailable("Migration requires an existing DELETE-mode journal")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            if _local_identity(source) != before_identity:
                raise JournalUnavailable("Migration database identity changed")
            row = db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()
            if row is None:
                raise JournalUnavailable("Missing storage version")
            if row[0] == PROTECTED_STORAGE_SCHEMA_VERSION:
                cls._validate_schema(db, PROTECTED_STORAGE_SCHEMA_VERSION)
                db.execute("ROLLBACK")
                return "ALREADY_MIGRATED"
            if row[0] != STORAGE_SCHEMA_VERSION:
                raise JournalUnavailable("Migration accepts exactly v5")
            cls._validate_schema(db, STORAGE_SCHEMA_VERSION)
            if (
                db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or db.execute("PRAGMA foreign_key_check").fetchone() is not None
            ):
                raise JournalUnavailable("Existing Journal integrity failed")
            for table in (*WORKFLOW_TABLES, *AUTHORITY_TABLES):
                if db.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()[0]:
                    raise JournalUnavailable("Existing workflow history requires separate upgrade")
            old_schema = _storage_schema_digest(db)
            accounting = _financial_snapshot_digest(db)
            create_v6_workflow_extension(db)
            db.execute("DROP TRIGGER require_storage_writer")
            cls._create_writer_guard(db, PROTECTED_STORAGE_SCHEMA_VERSION)
            _retarget_v4_writer_guards(db, PROTECTED_STORAGE_SCHEMA_VERSION, DETAIL_TABLES)
            _retarget_workflow_guards(db, {**WORKFLOW_TABLES, **AUTHORITY_TABLES}, PROTECTED_STORAGE_SCHEMA_VERSION)
            if fault_hook:
                fault_hook("before_version")
            db.execute("UPDATE schema_metadata SET version=6 WHERE singleton=1")
            if fault_hook:
                fault_hook("after_version")
            db.execute(
                "INSERT INTO workflow_storage_migrations VALUES(1,'v5-to-v6',5,6,?,?,?,?)",
                (old_schema, _storage_schema_digest(db), accounting, digest(asdict(writer))),
            )
            if fault_hook:
                fault_hook("after_receipt")
            cls._validate_schema(db, PROTECTED_STORAGE_SCHEMA_VERSION)
            if (
                _financial_snapshot_digest(db) != accounting
                or db.execute("PRAGMA foreign_key_check").fetchone() is not None
            ):
                raise JournalUnavailable("Migration changed accepted financial history")
            if fault_hook:
                fault_hook("before_commit")
            db.execute("COMMIT")
            if fault_hook:
                fault_hook("after_commit")
            return "MIGRATED"
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @classmethod
    def migrate_v1(cls, path: str | Path, writer: EvidenceRef, *, fault_hook=None) -> None:
        if not isinstance(writer, EvidenceRef) or not Path(path).is_file():
            raise JournalUnavailable("Explicit existing v1 database and trusted writer required")
        db = sqlite3.connect(str(path), isolation_level=None, timeout=1)
        db.row_factory = sqlite3.Row
        cls._register_writer(db)
        try:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise JournalUnavailable("Migration requires an existing DELETE-mode journal")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN EXCLUSIVE")
            row = db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()
            if row is None or row[0] != 1:
                raise JournalUnavailable("Migration accepts exactly v1")
            cls._validate_schema(db, 1)
            revisions: dict[str, int] = {}
            for event in db.execute("SELECT * FROM events ORDER BY scope,revision,ordinal"):
                revision = revisions.get(event["scope"], 0) + 1
                if (
                    event["revision"] != revision
                    or event["ordinal"] != 0
                    or digest(json.loads(event["payload"])) != event["digest"]
                ):
                    raise JournalUnavailable("Invalid v1 event sequence/digest")
                revisions[event["scope"]] = revision
            dummy = object.__new__(cls)
            dummy._owner = (os.getpid(), threading.get_ident())
            dummy._db = db
            dummy._create_v2_schema()
            cls._create_writer_guard(db)
            cls._create_v4_schema(db, writer_version=STORAGE_SCHEMA_VERSION)
            create_workflow_schema(db, writer_version=STORAGE_SCHEMA_VERSION)
            if fault_hook:
                fault_hook("before_version")
            db.execute("UPDATE schema_metadata SET version=? WHERE singleton=1", (STORAGE_SCHEMA_VERSION,))
            if fault_hook:
                fault_hook("after_version")
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @classmethod
    def migrate_v2(cls, path: str | Path, writer: EvidenceRef, *, fault_hook=None) -> None:
        cls._migrate_coverage(path, writer, 2, fault_hook=fault_hook)

    @classmethod
    def migrate_v3(cls, path: str | Path, writer: EvidenceRef, *, fault_hook=None) -> None:
        cls._migrate_coverage(path, writer, 3, fault_hook=fault_hook)

    @classmethod
    def migrate_v4(cls, path: str | Path, writer: EvidenceRef, *, fault_hook=None) -> None:
        if not isinstance(writer, EvidenceRef) or not Path(path).is_file():
            raise JournalUnavailable("Explicit existing v4 database and trusted writer required")
        db = sqlite3.connect(str(path), isolation_level=None, timeout=1)
        cls._register_writer(db)
        try:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise JournalUnavailable("Migration requires an existing DELETE-mode journal")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN EXCLUSIVE")
            row = db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()
            if row is None or row[0] != 4:
                raise JournalUnavailable("Migration accepts exactly v4")
            cls._validate_schema(db, 4)
            db.execute("DROP TRIGGER require_storage_writer")
            cls._create_writer_guard(db)
            _retarget_v4_writer_guards(db, STORAGE_SCHEMA_VERSION, DETAIL_TABLES)
            create_workflow_schema(db, writer_version=STORAGE_SCHEMA_VERSION)
            if fault_hook:
                fault_hook("before_version")
            db.execute("UPDATE schema_metadata SET version=? WHERE singleton=1", (STORAGE_SCHEMA_VERSION,))
            if fault_hook:
                fault_hook("after_version")
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @classmethod
    def _migrate_coverage(cls, path: str | Path, writer: EvidenceRef, version: int, *, fault_hook=None) -> None:
        """Validate and explicitly fence a v2 journal; never rewrite its history."""
        if not isinstance(writer, EvidenceRef) or not Path(path).is_file():
            raise JournalUnavailable("Explicit existing v2 database and trusted writer required")
        db = sqlite3.connect(str(path), isolation_level=None, timeout=1)
        db.row_factory = sqlite3.Row
        cls._register_writer(db)
        try:
            # Never checkpoint/convert an unsupported input before refusing it.
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise JournalUnavailable("Migration requires an existing DELETE-mode journal")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN EXCLUSIVE")
            row = db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()
            if row is None or row[0] != version:
                raise JournalUnavailable(f"Migration accepts exactly v{version}")
            cls._validate_schema(db, version)
            cls._validate_v2_history(db, version)
            if version >= 3:
                db.execute("DROP TRIGGER require_storage_writer")
            cls._create_writer_guard(db)
            cls._create_v4_schema(db, writer_version=STORAGE_SCHEMA_VERSION)
            create_workflow_schema(db, writer_version=STORAGE_SCHEMA_VERSION)
            if fault_hook:
                fault_hook("before_version")
            db.execute("UPDATE schema_metadata SET version=? WHERE singleton=1", (STORAGE_SCHEMA_VERSION,))
            if fault_hook:
                fault_hook("after_version")
            db.execute("COMMIT")
        except BaseException as exc:
            if db.in_transaction:
                db.execute("ROLLBACK")
            if isinstance(
                exc,
                (
                    sqlite3.Error,
                    KeyError,
                    IndexError,
                    AttributeError,
                    TypeError,
                    ValueError,
                    AssertionError,
                    RecursionError,
                ),
            ):
                raise JournalUnavailable("Invalid legacy v2 journal; migration refused") from exc
            raise
        finally:
            db.close()

    def _v2_indexes(self, indexes: list, identities: list) -> None:
        for item in identities:
            self._key(*item)
        if self.fault_hook:
            self.fault_hook("after_keys")
        for item in indexes:
            self._index(**item)
            if self.fault_hook:
                self.fault_hook("after_aliases" if item["table"] == "corroborating_finals" else "after_atoms")

    def _sync_baselines(self, scope: str, state: dict, revision: int) -> None:
        self._db.execute("DELETE FROM source_baselines WHERE scope=?", (scope,))
        for key, value in state.get("baselines", {}).items():
            self._db.execute("INSERT INTO source_baselines VALUES(?,?,?,?)", (scope, key, revision, canonical(value)))
        if self.fault_hook:
            self.fault_hook("after_baseline")

    def _commit_v2(
        self,
        scope: str,
        state: dict | None,
        revision: int,
        kind: str,
        after: dict,
        indexes: list,
        identities: list,
        evidence: dict,
    ) -> int:
        # Some observations pass state as after. Freeze before refreshing either.
        before = copy.deepcopy(state)
        after = _refresh_v2(copy.deepcopy(after))
        self._v2_indexes(indexes, identities)
        payload = {
            "state_delta": _state_delta(before, after),
            "indexes": indexes,
            "identities": identities,
            "evidence": evidence,
        }
        revision = self._record(scope, before, revision, kind, payload)
        self._sync_baselines(scope, after, revision)
        return revision

    @staticmethod
    def _entry(table: str, key: object, scope: str, owner: str, payload: dict) -> dict:
        return {"table": table, "key": canonical(key), "scope": scope, "owner": owner, "payload": payload}
