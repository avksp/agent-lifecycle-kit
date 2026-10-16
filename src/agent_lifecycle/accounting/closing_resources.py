"""Closed-run retention and resource methods for the SQLite journal.

This module neither authenticates a provider receipt nor dispatches a model.
Callers must establish policy, route, validity and source authority externally.
Only a proven empty pending opening inventory is supported by this core.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sqlite3
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast as _validated_cast

from .closing_resource_admission import ClosureAdmissionMixin
from .contracts import (
    ROLES as ROLES,
)
from .contracts import (
    CleanupOutcome,
    EvidenceRef,
    MaintenanceRequest,
    canonical,
    digest,
    identity,
    utc_instant,
)
from .contracts import (
    ClosureOutcome as ClosureOutcome,
)
from .contracts import (
    RunClosure as RunClosure,
)
from .contracts import (
    uint as uint,
)
from .workflow_store import (
    DETAIL_TABLES,
    RETENTION_TABLES,
    JournalUnavailable,
)
from .workflow_store import (
    RevisionConflict as RevisionConflict,
)
from .workflow_store import (
    _BindingConflict as _BindingConflict,
)


@contextmanager
def _raw_parent(root: Path, relative: str):
    """Pin each private parent without following links; unsupported platforms refuse."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or os.unlink not in os.supports_dir_fd:
        raise JournalUnavailable("Safe private raw deletion unavailable on this platform")
    if not isinstance(relative, str) or not relative:
        raise JournalUnavailable("Invalid private raw path")
    path = Path(relative)
    if path.is_absolute() or any(part in ("", ".", "..") for part in relative.split("/")):
        raise JournalUnavailable("Invalid private raw path")
    descriptors = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for part in path.parts[:-1]:
            info = os.fstat(fd)
            if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
                raise JournalUnavailable("Private raw directory authority unavailable")
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        info = os.fstat(fd)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise JournalUnavailable("Private raw parent must be owned and 0700")
        yield fd, path.name
    except OSError as exc:
        raise JournalUnavailable("Private raw path is unavailable or unsafe") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _raw_read(parent: int, name: str, *, maximum: int = 16_777_216, links: int = 1):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != links
            or before.st_size > maximum
        ):
            raise JournalUnavailable("Private raw file must be bounded, owned, single-link and 0600")
        chunks, size = [], 0
        while chunk := os.read(fd, min(65_536, maximum + 1 - size)):
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise JournalUnavailable("Private raw file exceeds bound")
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise JournalUnavailable("Private raw file changed during read")
        return b"".join(chunks), {"device": before.st_dev, "inode": before.st_ino}
    finally:
        os.close(fd)


def _raw_ref(root: Path, ref: dict):
    if (
        not isinstance(ref, dict)
        or set(ref) != {"path", "sha256", "bytes"}
        or type(ref["bytes"]) is not int
        or not 0 <= ref["bytes"] <= 1_048_576
        or not isinstance(ref["sha256"], str)
        or len(ref["sha256"]) != 64
    ):
        raise JournalUnavailable("Bounded sealed raw reference required")
    with _raw_parent(root, ref["path"]) as (parent, name):
        raw, file_id = _raw_read(parent, name, maximum=1_048_576)
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise JournalUnavailable("Sealed raw reference changed")
    return raw, file_id


class JournalRetentionMixin(ClosureAdmissionMixin):
    _maintenance_deadline: float | None

    def _checkpoint(self, stage: str) -> None:
        if self.fault_hook:
            self.fault_hook(stage)
        if self._maintenance_deadline is not None and time.monotonic() >= self._maintenance_deadline:
            raise JournalUnavailable("Maintenance deadline expired; unfinished transaction rolled back")

    def _archive_state(self, scope: str, *, restore: bool = False) -> tuple[dict, int]:
        closed = self._closed_scope(scope)
        if closed is None:
            raise JournalUnavailable("Archive has no closed scope binding")
        value = _validated_cast(dict, self.closed_run(closed["run_id"]))
        archive = self._retained("archive_records", scope)
        summary = value["summary"]["scopes"][scope]
        if (
            archive is None
            or archive["closure_id"] != closed["closure_id"]
            or archive["revision"] != closed["revision"]
            or archive["summary_digest"] != value["summary_digest"]
            or digest(archive["state"]) != summary["financial_digest"]
            or self._financial_totals(archive["state"], archive["revision"]) != summary["totals"]
            or digest(archive["protection"]) != archive["protection_digest"]
        ):
            raise JournalUnavailable("Invalid closed financial archive")
        cancellations = archive["protection"].get("cancellations", [])
        if len(cancellations) != len({v["operation_id"] for v in cancellations}) or {
            v["operation_id"] for v in cancellations
        } != {k for k, v in archive["state"]["operations"].items() if v["state"] == "CANCELLED_WITH_NO_DISPATCH_PROOF"}:
            raise JournalUnavailable("Archived cancellation proof inventory mismatch")
        for cancellation in cancellations:
            EvidenceRef(**cancellation["proof"]).__post_init__()
            if "event_kind" in cancellation:
                op = archive["state"]["operations"][cancellation["operation_id"]]
                declaration = {
                    "operation": op["binding"],
                    "claim_id": op["claim_id"],
                    "proof": cancellation["proof"],
                    "state": op["state"],
                }
                if (
                    cancellation["event_kind"] not in ("IMPORT_OPENING", "IMPORT_EVIDENCE_COMPLETED")
                    or cancellation["opening_digest"] != archive["state"]["opening_import_digest"]
                    or cancellation["declaration_digest"] != digest(declaration)
                ):
                    raise JournalUnavailable("Archived imported cancellation binding mismatch")
        cleanup = self._retained("cleanup_receipts", closed["run_id"])
        if cleanup is not None and cleanup["archives"].get(scope) != digest(archive):
            raise JournalUnavailable("Archive differs from committed cleanup seal")
        identities, indexes, observations = (
            archive["protection"]["identities"],
            archive["protection"]["indexes"],
            archive["protection"]["observations"],
        )
        for item in identities:
            kind, key, owner_scope, owner, checksum = item
            if owner_scope != scope:
                raise JournalUnavailable("Archived identity has another owner scope")
            row = self._db.execute("SELECT * FROM identities WHERE kind=? AND key=?", (kind, canonical(key))).fetchone()
            expected = (kind, canonical(key), scope, owner, checksum)
            if row is None and restore:
                self._db.execute("INSERT INTO identities VALUES(?,?,?,?,?)", expected)
            elif row is None or tuple(row) != expected:
                raise JournalUnavailable("Archived global identity mismatch")
        actual = {(r[0], r[1]) for r in self._db.execute("SELECT kind,key FROM identities WHERE scope=?", (scope,))}
        if actual != {(v[0], canonical(v[1])) for v in identities}:
            raise JournalUnavailable("Undeclared archived financial identity")
        for entry in indexes:
            table = entry["table"]
            if table not in ("coverage_atoms", "corroborating_finals") or entry["scope"] != scope:
                raise JournalUnavailable("Unexpected archived financial index")
            expected = (entry["key"], scope, entry["owner"], digest(entry["payload"]), canonical(entry["payload"]))
            row = self._db.execute(f"SELECT * FROM {table} WHERE key=?", (entry["key"],)).fetchone()
            if row is None and restore:
                self._db.execute(f"INSERT INTO {table} VALUES(?,?,?,?,?)", expected)
            elif row is None or tuple(row) != expected:
                raise JournalUnavailable("Archived financial index mismatch")
        for table in ("coverage_atoms", "corroborating_finals"):
            actual = {r[0] for r in self._db.execute(f"SELECT key FROM {table} WHERE scope=?", (scope,))}
            if actual != {v["key"] for v in indexes if v["table"] == table}:
                raise JournalUnavailable("Undeclared archived financial index")
        for entry in observations:
            existing = self._retained("archive_observation_keys", entry["key"])
            if existing is None and restore:
                self._retain("archive_observation_keys", entry["key"], scope, "observation", entry["payload"])
            elif existing != entry["payload"]:
                raise JournalUnavailable("Archived observation protection mismatch")
        actual = {r[0] for r in self._db.execute("SELECT key FROM archive_observation_keys WHERE scope=?", (scope,))}
        if actual != {v["key"] for v in observations}:
            raise JournalUnavailable("Undeclared archived observation identity")
        self._exception_chain(closed["run_id"], restore=restore)
        return copy.deepcopy(archive["state"]), archive["revision"]

    def collect_closed_run(self, run_id: str, now_utc: str) -> CleanupOutcome:
        now = utc_instant(now_utc)
        with self._transaction():
            value = self.closed_run(run_id)
            if value is None:
                raise JournalUnavailable("Authoritative full-run closure required")
            c = self._closure_outcome(value, "CLOSED")
            args = (run_id, c.closure_id, c.summary_digest, c.scope_revisions, c.eligible_after)
            prior = self._retained("cleanup_receipts", run_id)
            if prior:
                for scope, _ in c.scope_revisions:
                    self._archive_state(scope)
                return CleanupOutcome(
                    "ALREADY_COLLECTED", *args, deleted_rows=prior["deleted_rows"], logical_status="COLLECTED"
                )
            if now < utc_instant(value["eligible_after"]):
                return CleanupOutcome("NOT_DUE", *args)
            if self._exception_chain(run_id):
                return CleanupOutcome("ACCOUNTING_RECONCILIATION_REQUIRED", *args)
            archives = {}
            for scope, revision in c.scope_revisions:
                self._checkpoint("before_archive")
                state, actual_revision, indexes, identities = self._live_facts(scope)
                live = self._db.execute("SELECT data,revision FROM scope_state WHERE scope=?", (scope,)).fetchone()
                if live is None or actual_revision != revision or tuple(live) != (canonical(state), revision):
                    raise JournalUnavailable("Closed live state/revision differs from replay")
                compact = self._financial_state(state)
                summary = value["summary"]["scopes"][scope]
                if (
                    digest(compact) != summary["financial_digest"]
                    or self._financial_totals(state, revision) != summary["totals"]
                ):
                    raise JournalUnavailable("Closed financial facts changed before collection")
                observations = []
                for entry in indexes:
                    if entry["table"] != "source_observations":
                        continue
                    raw = entry["payload"]
                    binding = {
                        "namespace": "raw",
                        "key": entry["key"],
                        "scope": scope,
                        "owner": "observation",
                        "digest": raw["observation_digest"],
                        "raw_digest": raw["raw_digest"],
                        "finals": raw.get("finals", {}),
                    }
                    observations.append(
                        {
                            "key": entry["key"],
                            "payload": {
                                "binding": binding,
                                "original_index_digest": digest(raw),
                                "closure_id": c.closure_id,
                            },
                        }
                    )
                protection = {
                    "identities": identities,
                    "indexes": [e for e in indexes if e["table"] in ("coverage_atoms", "corroborating_finals")],
                    "observations": observations,
                    "cancellations": self._cancellation_witnesses(scope, state),
                }
                archive = {
                    "closure_id": c.closure_id,
                    "summary_digest": c.summary_digest,
                    "revision": revision,
                    "state": compact,
                    "protection": protection,
                    "protection_digest": digest(protection),
                }
                self._retain("archive_records", scope, scope, c.closure_id, archive)
                self._checkpoint("after_archive_seal")
                for entry in observations:
                    self._retain("archive_observation_keys", entry["key"], scope, "observation", entry["payload"])
                self._archive_state(scope)
                archives[scope] = digest(archive)
                self._checkpoint("after_archive_indexes")
            counts = {table: 0 for table in DETAIL_TABLES}
            self._retention_scopes = frozenset(s for s, _ in c.scope_revisions)
            try:
                for scope in sorted(self._retention_scopes):
                    for table in DETAIL_TABLES:
                        counts[table] += self._db.execute(f"DELETE FROM {table} WHERE scope=?", (scope,)).rowcount
                        self._checkpoint("after_delete_" + table)
            finally:
                self._retention_scopes = frozenset()
            receipt = {
                "closure_id": c.closure_id,
                "summary_digest": c.summary_digest,
                "archives": archives,
                "deleted_rows": counts,
                "collected_at": now.isoformat(),
            }
            self._retain("cleanup_receipts", run_id, run_id, c.closure_id, receipt)
            self._checkpoint("after_cleanup_receipt")
            return CleanupOutcome("COLLECTED", *args, deleted_rows=counts, logical_status="COLLECTED")

    def maintenance(self, request: MaintenanceRequest) -> dict:
        request.__post_init__()
        if request.journal_identity != self.journal_identity:
            raise JournalUnavailable("Maintenance journal authority mismatch")
        duration = (utc_instant(request.work_deadline_utc) - utc_instant(request.now_utc)).total_seconds()
        self._maintenance_deadline = time.monotonic() + min(duration, 60)
        outcomes, failure = [], None
        try:
            rows = self._db.execute(
                "SELECT r.key FROM run_closures r WHERE NOT EXISTS "
                "(SELECT 1 FROM cleanup_receipts c WHERE c.key=r.key) AND NOT EXISTS "
                "(SELECT 1 FROM financial_exceptions e WHERE e.scope=r.key) "
                "ORDER BY json_extract(r.payload,'$.eligible_after'),r.key LIMIT ?",
                (request.candidate_limit,),
            ).fetchall()
            for row in rows:
                self._checkpoint("before_maintenance_candidate")
                outcome = self.collect_closed_run(row[0], request.now_utc)
                outcomes.append(asdict(outcome))
                if outcome.status == "NOT_DUE":
                    break
        except JournalUnavailable as exc:
            failure = str(exc)
        finally:
            self._maintenance_deadline = None
        result = {
            "status": "PARTIAL" if failure else "COMPLETE",
            "outcomes": outcomes,
            "failure": failure,
            "journal_identity": request.journal_identity,
            "request": asdict(request),
        }
        with self._transaction():
            key = uuid.uuid4().hex
            self._retain("maintenance_receipts", key, request.journal_identity, "logical", result)
        return result

    def reclaim_storage(self, request: MaintenanceRequest) -> dict:
        request.__post_init__()
        previous = self._maintenance_deadline
        duration = (utc_instant(request.work_deadline_utc) - utc_instant(request.now_utc)).total_seconds()
        self._maintenance_deadline = time.monotonic() + min(duration, 60)
        try:
            try:
                with self._write_admission():
                    return self._reclaim_storage(request)
            except JournalUnavailable as exc:
                if str(exc) != "Write admission deadline expired":
                    raise
                # Preserve the structured refusal contract. This expired path
                # cannot execute VACUUM; receipt admission may also be unavailable.
                self._maintenance_deadline = min(_validated_cast(float, self._maintenance_deadline), time.monotonic())
                return self._reclaim_storage(request)
        finally:
            self._maintenance_deadline = previous

    def _reclaim_storage(self, request: MaintenanceRequest) -> dict:
        """Bounded physical retry, independent of successful logical collection."""
        request.__post_init__()
        if request.journal_identity != self.journal_identity or self._db.in_transaction:
            raise JournalUnavailable("Idle authorized journal required for physical maintenance")

        def metrics():
            return {
                "page_count": self._db.execute("PRAGMA page_count").fetchone()[0],
                "freelist_count": self._db.execute("PRAGMA freelist_count").fetchone()[0],
                "file_bytes": self._path.stat().st_size,
            }

        before = metrics()
        duration = (utc_instant(request.work_deadline_utc) - utc_instant(request.now_utc)).total_seconds()
        deadline = min(_validated_cast(float, self._maintenance_deadline), time.monotonic() + min(duration, 60))

        def progress():
            if self.fault_hook:
                self.fault_hook("during_vacuum")
            return int(time.monotonic() >= deadline)

        self._db.set_progress_handler(progress, 1 if self.fault_hook else 1000)
        failure = None
        try:
            if time.monotonic() >= deadline:
                raise sqlite3.OperationalError("Physical maintenance deadline expired")
            self._db.execute("VACUUM")
        except sqlite3.Error as exc:
            failure = str(exc)
        finally:
            self._db.set_progress_handler(None, 0)
        result = {
            "status": "NEEDS_STORAGE_MAINTENANCE" if failure else "RECLAIMED",
            "before": before,
            "after_vacuum": metrics(),
            "failure": failure,
            "journal_identity": request.journal_identity,
            "request": asdict(request),
        }
        try:
            with self._transaction():
                self._retain("maintenance_receipts", uuid.uuid4().hex, request.journal_identity, "physical", result)
            result["receipt_status"] = "PERSISTED"
        except JournalUnavailable as exc:
            result["receipt_status"] = "UNAVAILABLE"
            result["receipt_error"] = str(exc)
        return result

    def _raw_authority(self, root: Path, authority_ref: dict) -> dict:
        raw, _ = _raw_ref(root, authority_ref)
        authority = json.loads(raw)
        required = {
            "schemaVersion",
            "rootPathSha256",
            "rootFileIdentity",
            "journalPath",
            "journalFileIdentity",
            "journalIdentity",
            "storageVersion",
            "writerDigest",
            "planDigest",
            "manifestRef",
            "lockRef",
            "allowedAction",
        }
        if (
            not isinstance(authority, dict)
            or set(authority) != required
            or authority["schemaVersion"] != "alk-r68b-maintenance-authority.v1"
            or authority["allowedAction"] != "RAW_RETENTION"
        ):
            raise JournalUnavailable("Pinned raw maintenance authority required")
        info = root.lstat()
        if (
            not root.is_absolute()
            or root.resolve() != root
            or root.is_symlink()
            or stat.S_IMODE(info.st_mode) != 0o700
            or authority["rootPathSha256"] != hashlib.sha256(os.fsencode(str(root))).hexdigest()
            or authority["rootFileIdentity"] != {"device": info.st_dev, "inode": info.st_ino}
            or root / authority["journalPath"] != self._path
            or authority["journalIdentity"] != self.journal_identity
            or authority["storageVersion"] != self._storage_version
            or authority["writerDigest"] != digest(asdict(self.writer))
        ):
            raise JournalUnavailable("Raw maintenance root/journal/writer authority mismatch")
        with _raw_parent(root, authority["journalPath"]) as (parent, name):
            journal = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(journal.st_mode)
                or stat.S_IMODE(journal.st_mode) != 0o600
                or journal.st_uid != os.geteuid()
                or journal.st_nlink != 1
                or authority["journalFileIdentity"] != {"device": journal.st_dev, "inode": journal.st_ino}
            ):
                raise JournalUnavailable("Raw maintenance journal file identity mismatch")
        manifest, _ = _raw_ref(root, authority["manifestRef"])
        lock, _ = _raw_ref(root, authority["lockRef"])
        from agent_lifecycle.contracts.errors import LifecycleError
        from agent_lifecycle.freeze import verify_plan_lock_envelope

        try:
            manifest, lock = json.loads(manifest), json.loads(lock)
            if (
                not isinstance(manifest, dict)
                or manifest.get("status") != "FROZEN"
                or not isinstance(lock, dict)
                or lock.get("schemaVersion") != "agent-plan-lock.v2"
                or digest(manifest) != authority["planDigest"]
            ):
                raise JournalUnavailable("Raw maintenance frozen plan mismatch")
            joined = verify_plan_lock_envelope(manifest, lock)
            declared = manifest.get("planFiles")
            if (
                not isinstance(declared, list)
                or not all(isinstance(p, str) for p in declared)
                or len(declared) != len(set(declared))
                or {entry["path"] for entry in joined["entries"]} != set(declared)
            ):
                raise JournalUnavailable("Raw maintenance frozen inventory membership mismatch")
        except (ValueError, TypeError, KeyError, LifecycleError) as exc:
            raise JournalUnavailable("Raw maintenance lock/manifest lineage mismatch") from exc
        # This verifies sealed metadata joins, not all plan-member filesystem bytes.
        return authority

    def register_raw_inventory(
        self, run_id: str, inventory_ref: dict, *, private_root: Path, authority_ref: dict
    ) -> dict:
        """Transfer one sealed attempt inventory before closure; no raw bodies in SQL."""
        identity(run_id)
        root = Path(private_root).absolute()
        with self._transaction():
            authority = self._raw_authority(root, authority_ref)
            raw, file_id = _raw_ref(root, inventory_ref)
            inventory = json.loads(raw)
            required = {
                "schemaVersion",
                "runId",
                "taskId",
                "attemptId",
                "planDigest",
                "journalAuthorityKind",
                "journalIdentity",
                "eventLog",
                "eventLogFileIdentity",
                "rootPathSha256",
                "rootFileIdentity",
                "workflowStateDigest",
                "sources",
            }
            if isinstance(inventory, dict) and "operationId" in inventory:
                required.add("operationId")
                if not isinstance(inventory["operationId"], str) or not inventory["operationId"]:
                    raise JournalUnavailable("Raw inventory operation identity is invalid")
            if (
                not isinstance(inventory, dict)
                or set(inventory) != required
                or inventory["schemaVersion"] != "alk-r68b-raw-inventory.v1"
                or inventory["runId"] != run_id
                or inventory["planDigest"] != authority["planDigest"]
                or inventory["journalIdentity"] != authority["journalIdentity"]
                or inventory["eventLog"] != authority["journalPath"]
                or inventory["eventLogFileIdentity"] != authority["journalFileIdentity"]
                or inventory["rootPathSha256"] != authority["rootPathSha256"]
                or inventory["rootFileIdentity"] != authority["rootFileIdentity"]
            ):
                raise JournalUnavailable("Sealed raw inventory authority mismatch")
            identity(inventory["taskId"])
            identity(inventory["attemptId"])
            files = copy.deepcopy(inventory["sources"])
            if not isinstance(files, list) or not 1 <= len(files) <= 64:
                raise JournalUnavailable("Bounded nonempty raw file inventory required")
            forbidden = {
                authority_ref["path"],
                authority["journalPath"],
                authority["manifestRef"]["path"],
                authority["lockRef"]["path"],
                inventory_ref["path"],
            }
            seen, total = set(), 0
            for entry in files:
                if not isinstance(entry, dict) or set(entry) != {
                    "kind",
                    "path",
                    "pathSha256",
                    "fileIdentity",
                    "sha256",
                    "bytes",
                }:
                    raise JournalUnavailable("Closed raw file declaration required")
                if (
                    entry["path"] in forbidden
                    or entry["path"] in seen
                    or Path(entry["path"]).name.startswith(".alk-delete-")
                ):
                    raise JournalUnavailable("Duplicate or protected raw file declaration")
                with _raw_parent(root, entry["path"]) as (parent, name):
                    body, current_id = _raw_read(parent, name)
                if (
                    type(entry["bytes"]) is not int
                    or entry["bytes"] != len(body)
                    or entry["fileIdentity"] != current_id
                    or entry["sha256"] != hashlib.sha256(body).hexdigest()
                    or entry["pathSha256"] != hashlib.sha256(os.fsencode(str(root / entry["path"]))).hexdigest()
                ):
                    raise JournalUnavailable("Raw file declaration changed")
                seen.add(entry["path"])
                total += len(body)
            if total > 16_777_216:
                raise JournalUnavailable("Aggregate raw inventory exceeds bound")
            files.append(
                {
                    "kind": "sealed-inventory",
                    **inventory_ref,
                    "fileIdentity": file_id,
                    "pathSha256": hashlib.sha256(os.fsencode(str(root / inventory_ref["path"]))).hexdigest(),
                }
            )
            operation = [inventory["operationId"]] if "operationId" in inventory else []
            key = "raw-inventory:" + digest([run_id, inventory["taskId"], inventory["attemptId"], *operation])
            payload = {
                "schemaVersion": "alk-r68b-per-run-raw-obligation.v1",
                "runId": run_id,
                "taskId": inventory["taskId"],
                "attemptId": inventory["attemptId"],
                "inventoryRef": inventory_ref,
                "authorityRef": authority_ref,
                "authority": authority,
                "files": files,
            }
            if operation:
                payload["operationId"] = inventory["operationId"]
            old = self._retained("maintenance_receipts", key)
            if self.closed_run(run_id) is not None and old != payload:
                raise JournalUnavailable("Cannot add raw obligations after full run closure")
            if (
                not self._db.execute(
                    "SELECT 1 FROM scope_state WHERE json_extract(data,'$.scope.run_id')=?", (run_id,)
                ).fetchone()
                and old is None
            ):
                raise JournalUnavailable("Authoritative run required before inventory transfer")
            self._retain("maintenance_receipts", key, run_id, "raw-obligation", payload)
            return {"status": "PENDING", "obligationId": key, "inventorySha256": inventory_ref["sha256"]}

    def raw_obligations(self, run_id: str, now_utc: str) -> list[dict]:
        """Enumerate separately from SQL cleanup receipts, retaining every attempt."""
        identity(run_id)
        now, closed = utc_instant(now_utc), self.closed_run(run_id)
        values = []
        for row in self._db.execute(
            "SELECT key FROM maintenance_receipts WHERE scope=? AND owner='raw-obligation' ORDER BY key", (run_id,)
        ):
            payload = _validated_cast(dict, self._retained("maintenance_receipts", row[0]))
            done = self._retained("maintenance_receipts", "raw-done:" + digest(payload))
            eligible = closed["eligible_after"] if closed else None
            status = (
                "DONE"
                if done
                else "OVERDUE"
                if eligible and now > utc_instant(eligible) + timedelta(hours=2)
                else "PENDING"
            )
            values.append(
                {
                    "obligationId": row[0],
                    "inventorySha256": payload["inventoryRef"]["sha256"],
                    "taskId": payload["taskId"],
                    "attemptId": payload["attemptId"],
                    "status": status,
                    "closureId": closed["closure"]["closure_id"] if closed else None,
                    "summaryDigest": closed["summary_digest"] if closed else None,
                    "eligibleAfter": eligible,
                    "fileResults": done["fileResults"] if done else [],
                }
            )
        return values

    def _collect_raw_candidates(
        self,
        *,
        root: Path,
        run_id: str,
        candidate_limit: int,
        authority_ref: dict,
        authority: dict,
        require_live: Callable[[], None],
        read_source: Callable[..., None],
        present: Callable[[int, str], os.stat_result | None],
    ) -> list[tuple[str, dict, str, list[dict]]]:
        rows = self._db.execute(
            (
                "SELECT r.key FROM maintenance_receipts r WHERE r.scope=? AND "
                "r.owner='raw-obligation' AND NOT EXISTS (SELECT 1 FROM maintenance_receipts d "
                "WHERE d.key='raw-done:'||r.digest) ORDER BY r.key LIMIT ?"
            ),
            (run_id, candidate_limit),
        ).fetchall()
        completed = []
        for row in rows:
            payload = _validated_cast(dict, self._retained("maintenance_receipts", row[0]))
            if payload["authorityRef"] != authority_ref or payload["authority"] != authority:
                raise JournalUnavailable("Raw obligation pinned authority differs")
            result_key = "raw-done:" + digest(payload)
            if self._retained("maintenance_receipts", result_key):
                continue
            results = []
            for index, entry in enumerate(payload["files"]):
                self._checkpoint("before_raw_unlink")
                require_live()
                with _raw_parent(root, entry["path"]) as (parent, name):
                    quarantine = ".alk-delete-" + digest([row[0], index])
                    source, staged = (present(parent, name), present(parent, quarantine))
                    if source is not None and staged is None:
                        read_source(parent, name, entry)
                        self._checkpoint("before_raw_stage")
                        require_live()
                        if os.link not in os.supports_dir_fd or os.link not in os.supports_follow_symlinks:
                            raise JournalUnavailable("Atomic no-overwrite raw staging unavailable")
                        try:
                            os.link(name, quarantine, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                        except OSError as exc:
                            raise JournalUnavailable("Raw staging collision or unavailable; original retained") from exc
                        os.fsync(parent)
                        self._checkpoint("after_raw_stage")
                        source, staged = (present(parent, name), present(parent, quarantine))
                    if source is not None and staged is not None:
                        read_source(parent, name, entry, links=2)
                        read_source(parent, quarantine, entry, links=2)
                        require_live()
                        os.unlink(name, dir_fd=parent)
                        os.fsync(parent)
                        self._checkpoint("after_raw_original_unlink")
                    outcome = "alreadyAbsent"
                    if staged is not None:
                        read_source(parent, quarantine, entry)
                        require_live()
                        os.unlink(quarantine, dir_fd=parent)
                        os.fsync(parent)
                        outcome = "removed"
                    results.append({"pathSha256": entry["pathSha256"], "sha256": entry["sha256"], "status": outcome})
                self._checkpoint("after_raw_unlink")
            completed.append((row[0], payload, result_key, results))
        return completed

    def collect_raw_run(
        self,
        run_id: str,
        now_utc: str,
        *,
        private_root: Path,
        authority_ref: dict,
        candidate_limit: int = 32,
        work_deadline_utc: str | None = None,
    ) -> dict:
        """Collect sealed SQLite obligations under their registration/closure writer fence.

        ``now_utc`` is an as-of display value; only the runtime clock authorizes
        deletion. Producers hand off immutable files at registration. Arbitrary
        filesystem writers outside that handoff are not a protected host boundary.
        """
        identity(run_id)
        root = Path(private_root).absolute()
        utc_instant(now_utc)
        if type(candidate_limit) is not int or not 1 <= candidate_limit <= 32:
            raise JournalUnavailable("Bounded raw maintenance candidate limit required")
        started = time.monotonic()
        previous_utc, previous_mono = None, started

        def sample_clock():
            nonlocal previous_utc, previous_mono
            try:
                value, mono = self._utc_clock(), time.monotonic()
                if (
                    not isinstance(value, datetime)
                    or value.tzinfo is None
                    or value.utcoffset() != timedelta(0)
                    or not math.isfinite(mono)
                    or mono < previous_mono
                    or (previous_utc is not None and value < previous_utc)
                ):
                    raise ValueError("Unavailable or backward runtime clock")
                if (
                    previous_utc is not None
                    and abs((value - previous_utc).total_seconds() - (mono - previous_mono)) > 5
                ):
                    raise ValueError("Inconsistent runtime clocks")
            except Exception as exc:
                raise JournalUnavailable("Trusted raw maintenance clock unavailable or inconsistent") from exc
            previous_utc, previous_mono = value, mono
            return value, mono

        with self._transaction():
            authority = self._raw_authority(root, authority_ref)
            self._checkpoint("before_raw_eligibility")
            now, mono = sample_clock()
            deadline = min(
                utc_instant(work_deadline_utc) if work_deadline_utc else now + timedelta(seconds=60),
                now + timedelta(seconds=60),
            )
            monotonic_deadline = min(started + 60, mono + (deadline - now).total_seconds())
            if self._maintenance_deadline is not None:
                monotonic_deadline = min(monotonic_deadline, self._maintenance_deadline)
            if now >= deadline or mono >= monotonic_deadline:
                raise JournalUnavailable("Raw maintenance finite original deadline exhausted")
            closed = self.closed_run(run_id)
            if not closed:
                return {"status": "RUN_NOT_FULLY_CLOSED", "obligations": self.raw_obligations(run_id, now_utc)}
            if now < utc_instant(closed["eligible_after"]):
                return {"status": "NOT_DUE", "obligations": self.raw_obligations(run_id, now_utc)}
            if self._exception_chain(run_id):
                return {
                    "status": "ACCOUNTING_RECONCILIATION_REQUIRED",
                    "obligations": self.raw_obligations(run_id, now_utc),
                }
            if self._retained("cleanup_receipts", run_id) is None:
                raise JournalUnavailable("SQL collection must commit before raw unlink")

            def require_live():
                if (
                    self._raw_authority(root, authority_ref) != authority
                    or self.closed_run(run_id) != closed
                    or self._exception_chain(run_id)
                ):
                    raise JournalUnavailable("Raw retention eligibility changed under writer lock")
                current_utc, current_mono = sample_clock()
                if current_utc >= deadline or current_mono >= monotonic_deadline:
                    raise JournalUnavailable("Raw maintenance finite original deadline exhausted")
                if current_utc < utc_instant(closed["eligible_after"]):
                    raise JournalUnavailable("Raw retention eligibility changed under writer lock")

            def read_source(parent, name, entry, *, links=1):
                body, file_id = _raw_read(parent, name, links=links)
                if (
                    file_id != entry["fileIdentity"]
                    or len(body) != entry["bytes"]
                    or hashlib.sha256(body).hexdigest() != entry["sha256"]
                ):
                    raise JournalUnavailable("Raw source identity mismatch; staging retained")

            def present(parent, name):
                try:
                    return os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    return None

            completed = self._collect_raw_candidates(
                root=root,
                run_id=run_id,
                candidate_limit=candidate_limit,
                authority_ref=authority_ref,
                authority=authority,
                require_live=require_live,
                read_source=read_source,
                present=present,
            )
            # Defer every DONE seal until all selected obligations have been deleted.
            # A later obligation must not recreate a name belonging to an earlier one.
            for _ in completed:
                self._checkpoint("before_raw_done")
            require_live()
            for key, payload, _result_key, _results in completed:
                for index, entry in enumerate(payload["files"]):
                    with _raw_parent(root, entry["path"]) as (parent, name):
                        if (
                            present(parent, name) is not None
                            or present(parent, ".alk-delete-" + digest([key, index])) is not None
                        ):
                            raise JournalUnavailable("Raw names recreated before DONE; obligation remains pending")
            require_live()
            for _key, _payload, result_key, results in completed:
                self._retain(
                    "maintenance_receipts",
                    result_key,
                    run_id,
                    "raw-result",
                    {
                        "closureId": closed["closure"]["closure_id"],
                        "summaryDigest": closed["summary_digest"],
                        "authoritySha256": authority_ref["sha256"],
                        "fileResults": results,
                    },
                )
            obligations = self.raw_obligations(run_id, now_utc)
            return {
                "status": "DONE" if all(v["status"] == "DONE" for v in obligations) else "PENDING",
                "obligations": obligations,
            }

    def history_metadata(self, scope: str) -> dict:
        closed = self._closed_scope(scope)
        if closed is None:
            state, revision = self._load(scope)
            return {"status": "LIVE" if state is not None else "NOT_FOUND", "revision": revision}
        value = _validated_cast(dict, self.closed_run(closed["run_id"]))
        collected = self._retained("cleanup_receipts", closed["run_id"])
        return {
            "status": "DETAILS_COLLECTED" if collected else "CLOSED_DETAILS_RETAINED",
            "revision": closed["revision"],
            "closure_id": closed["closure_id"],
            "summary_digest": value["summary_digest"],
            "eligible_after": value["eligible_after"],
        }

    @staticmethod
    def _create_v4_schema(db: sqlite3.Connection, *, writer_version: int = 4) -> None:
        for table in RETENTION_TABLES:
            db.execute(
                f"CREATE TABLE {table}(key TEXT PRIMARY KEY NOT NULL, scope "
                "TEXT NOT NULL, owner TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'immutable financial archive'); END"
                )
        db.execute(
            "CREATE TABLE closed_scopes(scope TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT "
            "NULL, closure_id TEXT NOT NULL, revision INTEGER NOT NULL, summary_digest TEXT "
            "NOT NULL)"
        )
        db.execute(
            "CREATE TABLE exception_heads(run_id TEXT PRIMARY KEY NOT NULL, ordinal INTEGER "
            "NOT NULL, digest TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE retention_metadata(singleton INTEGER PRIMARY KEY "
            "CHECK(singleton=1), journal_id TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TRIGGER protect_exception_heads_delete BEFORE DELETE ON exception_heads "
            "BEGIN SELECT RAISE(ABORT,'immutable exception head'); END"
        )
        for action in ("INSERT", "UPDATE"):
            db.execute(
                f"CREATE TRIGGER guard_exception_heads_{action.lower()} BEFORE {action} ON exception_heads "
                f"WHEN alk_storage_writer_version() IS NOT {writer_version} OR "
                f"(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT {writer_version} "
                "BEGIN SELECT RAISE(ABORT,'incompatible exception writer'); END"
            )
        db.execute("INSERT INTO retention_metadata VALUES(1,?)", (uuid.uuid4().hex,))
        for table in ("closed_scopes", "retention_metadata"):
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'immutable closure binding'); END"
                )
        for table in DETAIL_TABLES:
            if table in ("events", "input_evidence", "source_profiles", "source_observations"):
                db.execute(f"DROP TRIGGER protect_{table}_delete")
            # Active baseline recomputation remains valid; closed scopes require the same retention context.
            condition = (
                "EXISTS(SELECT 1 FROM archive_records WHERE scope=OLD.scope) AND "
                if table == "source_baselines"
                else ""
            )
            db.execute(
                f"CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} WHEN "
                + condition
                + f"(alk_storage_writer_version() IS NOT {writer_version} OR "
                f"(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT {writer_version} OR "
                "alk_retention_scope(OLD.scope) IS NOT 1 OR "
                "NOT EXISTS(SELECT 1 FROM archive_records WHERE scope=OLD.scope)) "
                "BEGIN SELECT RAISE(ABORT,'sealed scoped collection required'); END"
            )
