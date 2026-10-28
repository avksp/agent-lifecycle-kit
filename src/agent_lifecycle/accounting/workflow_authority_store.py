"""D-AUTH tables in the same admitted SQLite journal as workflow and accounting."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast as _validated_cast

from agent_lifecycle.contracts.authority_io import read_authority_bytes, resolve_authority_anchor
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.deadline_schemas import utc_microseconds
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_authority import (
    validate_initial_authority_inputs,
    verify_signed_authority_snapshot,
)
from agent_lifecycle.contracts.workflow_authority_schemas import validate_bootstrap_pin, validate_run_output_anchor
from agent_lifecycle.contracts.workflow_state_authority import (
    decode_workflow_authority,
    validate_workflow_authority,
)
from agent_lifecycle.contracts.workflow_state_schemas import (
    has_current_workflow_semantics,
    validate_adoption_input,
    validate_adoption_selection,
    validate_runtime_binding,
)
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation

from .contracts import JournalUnavailable, canonical, digest

AUTHORITY_TABLES = {
    "workflow_authority_roots": (
        "binding_id TEXT PRIMARY KEY NOT NULL, root_digest TEXT NOT NULL, payload TEXT NOT NULL",
        False,
    ),
    "workflow_authority_snapshots": (
        "binding_id TEXT NOT NULL, epoch INTEGER NOT NULL CHECK(epoch>=0), snapshot_digest TEXT NOT NULL, "
        "predecessor_digest TEXT, install_operation_id TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(binding_id,epoch)",
        False,
    ),
    "workflow_authority_current": (
        "binding_id TEXT PRIMARY KEY NOT NULL, epoch INTEGER NOT NULL CHECK(epoch>=0), "
        "snapshot_digest TEXT NOT NULL, accepted_utc TEXT NOT NULL",
        True,
    ),
    "workflow_authority_decisions": (
        "decision_kind TEXT NOT NULL, run_id TEXT NOT NULL, operation_or_claim_id TEXT NOT NULL, "
        "decision_digest TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(decision_kind,run_id,operation_or_claim_id)",
        False,
    ),
}


def _create_v4_writer_guards(db: sqlite3.Connection, writer_version: int, detail_tables: tuple[str, ...]) -> None:
    for action in ("INSERT", "UPDATE"):
        db.execute(
            f"CREATE TRIGGER guard_exception_heads_{action.lower()} BEFORE {action} ON exception_heads "
            f"WHEN alk_storage_writer_version() IS NOT {writer_version} OR "
            f"(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT {writer_version} "
            "BEGIN SELECT RAISE(ABORT,'incompatible exception writer'); END"
        )
    for table in detail_tables:
        # Active baseline recomputation remains valid; closed scopes require the same retention context.
        condition = (
            "EXISTS(SELECT 1 FROM archive_records WHERE scope=OLD.scope) AND " if table == "source_baselines" else ""
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


def _retarget_v4_writer_guards(db: sqlite3.Connection, writer_version: int, detail_tables: tuple[str, ...]) -> None:
    for action in ("insert", "update"):
        db.execute(f"DROP TRIGGER guard_exception_heads_{action}")
    for table in detail_tables:
        db.execute(f"DROP TRIGGER protect_{table}_delete")
    _create_v4_writer_guards(db, writer_version, detail_tables)


def _retarget_workflow_guards(db: sqlite3.Connection, tables: dict, writer_version: int) -> None:
    for table, (_, mutable) in tables.items():
        for action in ("INSERT", "UPDATE") if mutable else ("INSERT",):
            db.execute(f"DROP TRIGGER guard_{table}_{action.lower()}")
            db.execute(
                f"CREATE TRIGGER guard_{table}_{action.lower()} BEFORE {action} ON {table} "
                f"WHEN alk_storage_writer_version() IS NOT {writer_version} OR "
                f"(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT {writer_version} "
                "BEGIN SELECT RAISE(ABORT,'incompatible workflow writer'); END"
            )


def create_v6_workflow_extension(db: sqlite3.Connection) -> None:
    """Install fail-closed v6 anchor, staged body and migration receipt storage."""
    db.execute(
        "CREATE TABLE workflow_run_output_anchors("
        "run_id TEXT PRIMARY KEY NOT NULL REFERENCES workflow_bindings(run_id), "
        "binding_digest TEXT NOT NULL, adopted_state_digest TEXT NOT NULL, journal_identity TEXT NOT NULL, "
        "artifact_root_path TEXT NOT NULL, root_platform TEXT NOT NULL, root_volume_id TEXT NOT NULL, "
        "root_file_id TEXT NOT NULL, package_root TEXT NOT NULL, event_log TEXT NOT NULL, "
        "output_root_relative_path TEXT NOT NULL, canonical_anchor_bytes BLOB NOT NULL, "
        "anchor_digest TEXT NOT NULL, storage_version INTEGER NOT NULL CHECK(storage_version=6))"
    )
    db.execute(
        "CREATE TABLE workflow_proof_body_stage("
        "run_id TEXT NOT NULL REFERENCES workflow_run_output_anchors(run_id), "
        "producer_operation_id TEXT NOT NULL, producer_request_digest TEXT NOT NULL, "
        "anchor_digest TEXT NOT NULL, prepared_input_bytes BLOB NOT NULL, "
        "prepared_input_length INTEGER NOT NULL CHECK(prepared_input_length BETWEEN 1 AND 1048576), "
        "prepared_input_sha256 TEXT NOT NULL, body_bytes BLOB NOT NULL, body_sha256 TEXT NOT NULL, "
        "body_length INTEGER NOT NULL CHECK(body_length BETWEEN 1 AND 1048576), "
        "authority_decision_ref BLOB NOT NULL, deadline_decision_ref BLOB NOT NULL, "
        "clock_observation_ref BLOB NOT NULL, "
        "publication_status TEXT NOT NULL CHECK(publication_status IN ('PENDING','ACK')), "
        "ack_digest TEXT, PRIMARY KEY(run_id,producer_operation_id))"
    )
    db.execute(
        "CREATE TABLE workflow_storage_migrations("
        "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
        "migration_id TEXT NOT NULL UNIQUE CHECK(migration_id IN ('init-v6','v5-to-v6')), "
        "from_version INTEGER, to_version INTEGER NOT NULL CHECK(to_version=6), "
        "old_schema_digest TEXT, new_schema_digest TEXT NOT NULL, "
        "accounting_snapshot_digest TEXT NOT NULL, writer_identity_digest TEXT NOT NULL)"
    )
    for table in ("workflow_run_output_anchors", "workflow_proof_body_stage", "workflow_storage_migrations"):
        db.execute(
            f"CREATE TRIGGER guard_{table}_insert BEFORE INSERT ON {table} WHEN "
            "alk_storage_writer_version() IS NOT 6 OR "
            "(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT 6 "
            "BEGIN SELECT RAISE(ABORT,'incompatible workflow writer'); END"
        )
    db.execute(
        "CREATE TRIGGER validate_workflow_run_output_anchors_insert "
        "BEFORE INSERT ON workflow_run_output_anchors WHEN "
        "alk_anchor_digest(NEW.canonical_anchor_bytes) IS NOT NEW.anchor_digest OR "
        "alk_anchor_row_matches(NEW.canonical_anchor_bytes,NEW.run_id,NEW.binding_digest,"
        "NEW.adopted_state_digest,NEW.journal_identity,NEW.artifact_root_path,NEW.root_platform,"
        "NEW.root_volume_id,NEW.root_file_id,NEW.package_root,NEW.event_log,"
        "NEW.output_root_relative_path) IS NOT 1 "
        "BEGIN SELECT RAISE(ABORT,'invalid run output anchor'); END"
    )
    db.execute(
        "CREATE TRIGGER validate_workflow_proof_body_stage_insert "
        "BEFORE INSERT ON workflow_proof_body_stage WHEN "
        "NEW.publication_status IS NOT 'PENDING' OR NEW.ack_digest IS NOT NULL OR "
        "length(NEW.prepared_input_bytes) IS NOT NEW.prepared_input_length OR "
        "length(NEW.body_bytes) IS NOT NEW.body_length OR "
        "alk_canonical_json_sha256(NEW.prepared_input_bytes) IS NOT NEW.prepared_input_sha256 OR "
        "alk_canonical_json_sha256(NEW.body_bytes) IS NOT NEW.body_sha256 OR "
        "NOT EXISTS(SELECT 1 FROM workflow_run_output_anchors a WHERE "
        "a.run_id=NEW.run_id AND a.anchor_digest=NEW.anchor_digest) "
        "BEGIN SELECT RAISE(ABORT,'invalid proof body stage'); END"
    )
    unchanged = (
        "run_id",
        "producer_operation_id",
        "producer_request_digest",
        "anchor_digest",
        "prepared_input_bytes",
        "prepared_input_length",
        "prepared_input_sha256",
        "body_bytes",
        "body_sha256",
        "body_length",
        "authority_decision_ref",
        "deadline_decision_ref",
        "clock_observation_ref",
    )
    changed = " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in unchanged)
    db.execute(
        "CREATE TRIGGER guard_workflow_proof_body_stage_update BEFORE UPDATE "
        "ON workflow_proof_body_stage WHEN alk_storage_writer_version() IS NOT 6 OR "
        "(SELECT version FROM schema_metadata WHERE singleton=1) IS NOT 6 OR "
        "OLD.publication_status IS NOT 'PENDING' OR OLD.ack_digest IS NOT NULL OR "
        "NEW.publication_status IS NOT 'ACK' OR NEW.ack_digest IS NULL OR "
        "alk_stage_ack_verified() IS NOT 1 OR "
        f"{changed} BEGIN SELECT RAISE(ABORT,'invalid proof body ACK'); END"
    )
    for table in ("workflow_run_output_anchors", "workflow_storage_migrations"):
        for action in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END"
            )
    db.execute(
        "CREATE TRIGGER protect_workflow_proof_body_stage_delete BEFORE DELETE "
        "ON workflow_proof_body_stage BEGIN SELECT RAISE(ABORT,'immutable proof body stage'); END"
    )


def _storage_schema_digest(db: sqlite3.Connection) -> str:
    objects = [
        list(row)
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE type IN ('table','index','trigger') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type,name,tbl_name,sql"
        )
    ]
    return digest(objects)


def _anchor_digest(raw: object) -> str | None:
    """SQLite UDF accepts only exact canonical, schema-valid anchor bytes."""
    if type(raw) is not bytes or not 1 <= len(raw) <= 1_048_576:
        return None
    try:
        value = validate_run_output_anchor(load_json_object(raw, label="run output anchor"))
        if canonical_bytes(value) != raw:
            return None
    except (LifecycleError, TypeError, ValueError, RecursionError):
        return None
    return hashlib.sha256(raw).hexdigest()


def _anchor_row_matches(raw: object, *columns: object) -> int:
    """Keep duplicated SQL columns tied to one exact anchor; this proves no root custody."""
    if _anchor_digest(raw) is None:
        return 0
    try:
        value = load_json_object(_validated_cast(bytes, raw), label="run output anchor")
    except (LifecycleError, TypeError, ValueError, RecursionError):
        return 0
    root = value["artifactAuthorityRootIdentity"]
    expected = (
        value["runId"],
        value["bindingDigest"],
        value["adoptedStateDigest"],
        value["journalIdentity"],
        value["artifactAuthorityRootPath"],
        root["platform"],
        root["volumeId"],
        root["fileId"],
        value["packageRoot"],
        value["eventLog"],
        value["runOutputRootRelativePath"],
    )
    return int(columns == expected)


def _load_run_output_anchor_data(db: sqlite3.Connection, binding: dict, binding_digest: str) -> dict:
    """Read the v6 anchor's exact stored data; physical root custody is separate."""
    if binding.get("storageProtocolVersion") != "6" or canonical_digest(binding) != binding_digest:
        raise JournalUnavailable("Run output anchor requires v6 storage", write_outcome="NOT_STARTED")
    saved = db.execute(
        "SELECT binding_digest,payload FROM workflow_bindings WHERE run_id=?", (binding["runId"],)
    ).fetchone()
    if saved is None or saved["binding_digest"] != binding_digest or saved["payload"] != canonical(binding):
        raise JournalUnavailable("Pinned workflow binding is absent or changed", write_outcome="NOT_STARTED")
    row = db.execute("SELECT * FROM workflow_run_output_anchors WHERE run_id=?", (binding["runId"],)).fetchone()
    if row is None:
        raise JournalUnavailable("Pinned run output anchor is absent", write_outcome="NOT_STARTED")
    raw = row["canonical_anchor_bytes"]
    columns = tuple(
        row[name]
        for name in (
            "run_id",
            "binding_digest",
            "adopted_state_digest",
            "journal_identity",
            "artifact_root_path",
            "root_platform",
            "root_volume_id",
            "root_file_id",
            "package_root",
            "event_log",
            "output_root_relative_path",
        )
    )
    if (
        row["storage_version"] != 6
        or _anchor_digest(raw) != row["anchor_digest"]
        or _anchor_row_matches(raw, *columns) != 1
        or row["binding_digest"] != binding_digest
        or row["journal_identity"] != binding["journalIdentity"]
    ):
        raise JournalUnavailable("Run output anchor SQL identity differs", write_outcome="NOT_STARTED")
    anchor = load_json_object(raw, label="run output anchor")
    if anchor["canonicalStatePath"] != binding["canonicalStatePath"]:
        raise JournalUnavailable("Run output anchor state path differs", write_outcome="NOT_STARTED")
    return anchor


def _canonical_json_sha256(raw: object) -> str | None:
    """Bounded canonical object bytes only; semantic B/P refs need separate checks."""
    if type(raw) is not bytes or not 1 <= len(raw) <= 1_048_576:
        return None
    try:
        value = load_json_object(raw, label="proof body stage")
        if canonical_bytes(value) != raw:
            return None
    except (LifecycleError, TypeError, ValueError, RecursionError):
        return None
    return hashlib.sha256(raw).hexdigest()


def _financial_snapshot_digest(db: sqlite3.Connection) -> str:
    """Hash every retained financial row, independent of SQLite row iteration order."""
    tables = [
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        if not row[0].startswith(("workflow_", "sqlite_"))
        and row[0] != "schema_metadata"
        and not row[0].startswith(("closing_policy_", "closing_operation_", "closing_resource_", "closing_protection_"))
    ]
    rows = []
    for table in tables:
        values = []
        for row in db.execute(f"SELECT * FROM {table}"):
            record = [
                ["blob", item.hex()]
                if isinstance(item, bytes)
                else ["null", None]
                if item is None
                else ["integer", item]
                if type(item) is int
                else ["text", item]
                if type(item) is str
                else ["unsupported", type(item).__name__]
                for item in row
            ]
            if any(item[0] == "unsupported" for item in record):
                raise JournalUnavailable("Unknown financial snapshot value type")
            values.append(record)
        rows.append([table, sorted(values, key=canonical)])
    return digest(rows)


def _validate_v6_storage_receipt(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT * FROM workflow_storage_migrations").fetchall()
    if len(rows) != 1:
        raise JournalUnavailable("Missing or duplicate v6 storage migration receipt")
    receipt = rows[0]
    if receipt[0] != 1 or receipt[3] != 6:
        raise JournalUnavailable("Invalid v6 storage migration receipt")
    if receipt[1] == "init-v6":
        if receipt[2] is not None or receipt[4] is not None:
            raise JournalUnavailable("Invalid v6 initialization receipt")
    elif receipt[1] == "v5-to-v6":
        if receipt[2] != 5 or not isinstance(receipt[4], str) or re.fullmatch(r"[0-9a-f]{64}", receipt[4]) is None:
            raise JournalUnavailable("Invalid v5-to-v6 migration receipt")
    else:
        raise JournalUnavailable("Unknown v6 migration receipt")
    for value in (receipt[5], receipt[6], receipt[7]):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise JournalUnavailable("Invalid v6 migration digest")
    if receipt[5] != _storage_schema_digest(db):
        raise JournalUnavailable("V6 schema differs from migration receipt")


def validate_legacy_adoption_history(
    state: dict,
    events: list[dict],
    *,
    root: Path | None = None,
    state_path: Path | None = None,
    operation: StorageOperation | None = None,
) -> dict:
    """Refuse split or incomplete legacy history before any Journal adoption write."""
    validate_workflow_authority(state, root=root, state_path=state_path, operation=operation)
    if not has_current_workflow_semantics(state):
        raise LifecycleError("workflow-adoption-invalid", "Legacy state must complete explicit v4 migration")
    if type(events) is not list:
        raise LifecycleError("workflow-adoption-invalid", "Complete ordered event history is required")
    revision = state["stateRevision"]
    ledger = state["operationLedger"]
    if len(events) != revision - 1 or len(ledger) != len(events):
        raise LifecycleError("workflow-adoption-invalid", "Event and operation history are incomplete")
    seen: set[str] = set()
    for expected_revision, event in enumerate(events, start=2):
        operation_id = _require_legacy_event_identity(event, state, expected_revision, seen)
        _require_legacy_ledger_entry(ledger.get(operation_id), event, expected_revision)
        seen.add(operation_id)
    return {
        "schemaVersion": "agent-workflow-legacy-history-check.v1",
        "status": "DATA_CANDIDATE",
        "stateDigest": canonical_digest(state),
        "historyDigest": canonical_digest(events),
        "eventCount": len(events),
        "operationIds": sorted(seen),
        "quiescenceQualified": False,
        "accountingHistoryQualified": False,
        "nativePermissionGranted": False,
    }


def _require_legacy_event_identity(event: dict, state: dict, expected_revision: int, seen: set[str]) -> str:
    fields = {
        "schemaVersion",
        "runId",
        "packageId",
        "stateRevision",
        "operationId",
        "eventType",
        "payload",
        "recordedAt",
    }
    if type(event) is not dict or set(event) != fields:
        raise LifecycleError("workflow-adoption-invalid", "Legacy event has missing or unknown fields")
    operation_id = event["operationId"]
    if (
        event["schemaVersion"] != "agent-workflow-event.v1"
        or event["runId"] != state["runId"]
        or event["packageId"] != state["packageId"]
        or type(event["stateRevision"]) is not int
        or event["stateRevision"] != expected_revision
        or type(operation_id) is not str
        or not 1 <= len(operation_id) <= 256
        or operation_id in seen
        or type(event["eventType"]) is not str
        or not event["eventType"]
        or type(event["payload"]) is not dict
        or type(event["recordedAt"]) is not str
        or not event["recordedAt"]
    ):
        raise LifecycleError("workflow-adoption-invalid", "Legacy event identity or order differs")
    return operation_id


def _require_legacy_ledger_entry(entry: object, event: dict, expected_revision: int) -> None:
    if (
        type(entry) is not dict
        or set(entry) != {"stateRevision", "eventType", "recordedAt"}
        or type(entry["stateRevision"]) is not int
        or entry["stateRevision"] != expected_revision
        or entry["eventType"] != event["eventType"]
        or type(entry["recordedAt"]) is not str
        or not entry["recordedAt"]
        or entry["recordedAt"] != event["recordedAt"]
    ):
        raise LifecycleError("workflow-adoption-invalid", "Operation ledger differs from event history")


def _adoption_artifact(root: Path, ref: dict) -> bytes:
    relative = normalize_repo_path(ref["path"], label="adoption artifact")
    raw = read_authority_bytes(root / relative, max_bytes=8_388_608, root=root)
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise LifecycleError("workflow-adoption-invalid", "Adoption artifact bytes differ")
    return raw


def prepare_legacy_adoption_candidate(
    adoption_input: dict,
    selection: dict,
    *,
    artifact_root: Path,
    observed_at: str,
) -> dict:
    """Read exact legacy inputs; no caller provenance, accounting authority or write is inferred."""
    validate_adoption_input(adoption_input)
    validate_adoption_selection(selection)
    root = Path(artifact_root).resolve(strict=True)
    binding = load_json_object(_adoption_artifact(root, adoption_input["bindingRef"]), label="adoption binding")
    validate_runtime_binding(binding)
    if (
        canonical_digest(binding) != selection["expectedBindingDigest"]
        or binding["journalIdentity"] != selection["expectedJournalIdentity"]
        or binding["budgetScopeId"] != selection["expectedBudgetScopeId"]
        or binding["storageProtocolVersion"] != selection["expectedStorageProtocolVersion"]
        or binding["workflowProtocolVersion"] != selection["expectedWorkflowProtocolVersion"]
    ):
        raise LifecycleError("workflow-adoption-invalid", "Selected runtime binding differs")
    state_ref = adoption_input["legacyStateRef"]
    if normalize_repo_path(state_ref["path"], label="legacy state") != normalize_repo_path(
        binding["canonicalStatePath"], label="bound state"
    ):
        raise LifecycleError("workflow-adoption-invalid", "Legacy state path differs from binding")
    state_raw = _adoption_artifact(root, state_ref)
    state = load_json_object(state_raw, label="legacy workflow state")
    if (
        not has_current_workflow_semantics(state)
        or state["runId"] != binding["runId"]
        or state["packageId"] != binding["packageId"]
        or state.get("planDigest") != binding["planDigest"]
        or state.get("sourceRevision") != binding["sourceRevision"]
    ):
        raise LifecycleError("workflow-adoption-invalid", "Legacy state identity differs from binding")
    state_path = root / state_ref["path"]
    anchor = resolve_authority_anchor(state_path, state.get("packageRoot", "."), root=root)
    events = _read_adoption_events(root, anchor, state, adoption_input)
    with StorageOperation(anchor, state_path=state_path, run_id=state["runId"]) as operation:
        state = decode_workflow_authority(state_raw, root=anchor, state_path=state_path, operation=operation)
        history = validate_legacy_adoption_history(
            state, events, root=anchor, state_path=state_path, operation=operation
        )
    snapshot_raw = _adoption_artifact(root, adoption_input["initialSnapshotRef"])
    if len(snapshot_raw) > 1_048_576:
        raise LifecycleError("workflow-adoption-invalid", "Initial snapshot exceeds authority byte limit")
    snapshot = load_json_object(snapshot_raw, label="initial authority snapshot")
    pin_raw = _adoption_artifact(root, binding["workflowAuthorityPinRef"])
    pin = validate_bootstrap_pin(load_json_object(pin_raw, label="workflow authority pin"))
    qualification_raw = _adoption_artifact(root, pin["qualificationRef"])
    for name in ("operatorQualificationRef", "quiescenceEvidenceRef", "writerInventoryRef"):
        _adoption_artifact(root, selection[name])
    authority = validate_initial_authority_inputs(
        binding,
        selection["expectedBindingDigest"],
        selection["expectedPinDigest"],
        pin_raw,
        qualification_raw,
        snapshot,
        observed_at=observed_at,
    )
    if authority["snapshotDigest"] != selection["expectedInitialSnapshotDigest"]:
        raise LifecycleError("workflow-adoption-invalid", "Selected initial snapshot differs")
    return {
        "schemaVersion": "agent-workflow-adoption-candidate.v1",
        "status": "DATA_CANDIDATE",
        "runId": binding["runId"],
        "budgetScopeId": binding["budgetScopeId"],
        "operationId": adoption_input["operationId"],
        "inputDigest": canonical_digest(adoption_input),
        "selectionDigest": canonical_digest(selection),
        "bindingDigest": authority["bindingDigest"],
        "pinDigest": authority["pinDigest"],
        "snapshotDigest": authority["snapshotDigest"],
        "stateDigest": history["stateDigest"],
        "historyDigest": history["historyDigest"],
        "eventCount": history["eventCount"],
        "operationIds": history["operationIds"],
        "expectedAccountingRevision": selection["expectedAccountingRevision"],
        "expectedAccountingStateDigest": selection["expectedAccountingStateDigest"],
        "operatorQualified": False,
        "quiescenceQualified": False,
        "accountingHistoryQualified": False,
        "financialAdmission": False,
        "nativePermissionGranted": False,
    }


def _read_adoption_events(root: Path, anchor: Path, state: dict, adoption_input: dict) -> list[dict]:
    event_path = anchor / normalize_repo_path(state["eventLog"], label="legacy event log")
    try:
        event_relative = event_path.relative_to(root).as_posix()
    except ValueError:
        raise LifecycleError("workflow-adoption-invalid", "Legacy event log escapes selected root") from None
    event_ref = adoption_input["legacyEventLogRef"]
    if event_ref is None:
        if state["stateRevision"] != 1 or state["operationLedger"]:
            raise LifecycleError("workflow-adoption-invalid", "Missing legacy event prefix")
        try:
            read_authority_bytes(root / event_relative, max_bytes=8_388_608, root=root)
        except FileNotFoundError:
            event_raw = b""
        else:
            raise LifecycleError("workflow-adoption-invalid", "Existing event log requires an exact ref")
    else:
        if normalize_repo_path(event_ref["path"], label="event ref") != event_relative:
            raise LifecycleError("workflow-adoption-invalid", "Legacy event path differs from state")
        event_raw = _adoption_artifact(root, event_ref)
    events = []
    for line in event_raw.splitlines():
        if not line.strip():
            raise LifecycleError("workflow-adoption-invalid", "Blank legacy event line")
        events.append(load_json_object(line, label="legacy event"))
    return events


def _loaded_root(db: sqlite3.Connection, binding: dict, binding_digest: str) -> dict:
    """A missing qualified bootstrap is unavailable, never a new self-selected root."""
    row = db.execute(
        "SELECT root_digest,payload FROM workflow_authority_roots WHERE binding_id=?", (binding["bindingId"],)
    ).fetchone()
    if row is None:
        raise JournalUnavailable("Qualified workflow root bootstrap is absent", write_outcome="NOT_STARTED")
    try:
        value = json.loads(row["payload"])
        if (
            type(value) is not dict
            or set(value) != {"pin", "pinRef", "bindingDigest", "qualificationDigest"}
            or canonical(value) != row["payload"]
            or value["bindingDigest"] != binding_digest
            or value["pinRef"] != binding["workflowAuthorityPinRef"]
            or type(value["qualificationDigest"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["qualificationDigest"]) is None
        ):
            raise ValueError("Root bootstrap record mismatch")
        pin = validate_bootstrap_pin(value["pin"])
        if canonical_digest(pin) != row["root_digest"]:
            raise ValueError("Pinned root digest mismatch")
        if value["qualificationDigest"] != pin["qualificationRef"]["sha256"]:
            raise ValueError("Root qualification digest mismatch")
        for left, right in (
            ("bindingId", "bindingId"),
            ("runId", "runId"),
            ("budgetScopeId", "budgetScopeId"),
            ("journalIdentity", "journalIdentity"),
        ):
            if pin[left] != binding[right]:
                raise ValueError("Root identity differs from runtime binding")
        return pin
    except (TypeError, ValueError, KeyError, RecursionError, LifecycleError) as exc:
        raise JournalUnavailable("Invalid qualified workflow root record", write_outcome="NOT_STARTED") from exc


def _snapshot_row(db: sqlite3.Connection, binding_id: str, epoch: int) -> tuple[dict, str]:
    row = db.execute(
        "SELECT snapshot_digest,payload FROM workflow_authority_snapshots WHERE binding_id=? AND epoch=?",
        (binding_id, epoch),
    ).fetchone()
    if row is None:
        raise JournalUnavailable("Current authority snapshot is absent", write_outcome="NOT_STARTED")
    try:
        snapshot = json.loads(row["payload"])
        if canonical(snapshot) != row["payload"] or canonical_digest(snapshot) != row["snapshot_digest"]:
            raise ValueError("Snapshot digest mismatch")
        return snapshot, row["snapshot_digest"]
    except (TypeError, ValueError, RecursionError) as exc:
        raise JournalUnavailable("Invalid authority snapshot record", write_outcome="NOT_STARTED") from exc


def _monotonic_successor(previous: dict, next_snapshot: dict) -> bool:
    old_issuers = {(x["issuerId"], x["issuerGeneration"]): x for x in previous["activeIssuers"]}
    new_issuers = {(x["issuerId"], x["issuerGeneration"]): x for x in next_snapshot["activeIssuers"]}
    revoked_issuers = {(x["issuerId"], x["issuerGeneration"]) for x in next_snapshot["revokedIssuers"]}
    old_revoked_issuers = {(x["issuerId"], x["issuerGeneration"]) for x in previous["revokedIssuers"]}
    revoked_grants = {(x["issuerId"], x["issuerGeneration"], x["nonce"]) for x in next_snapshot["revokedGrants"]}
    old_revoked_grants = {(x["issuerId"], x["issuerGeneration"], x["nonce"]) for x in previous["revokedGrants"]}
    return (
        old_revoked_issuers <= revoked_issuers
        and old_revoked_grants <= revoked_grants
        and set(old_issuers) - set(new_issuers) <= revoked_issuers
        and all(old_issuers[key] == new_issuers[key] for key in old_issuers.keys() & new_issuers.keys())
    )


def _revocation_only_successor(previous: dict, next_snapshot: dict) -> bool:
    """Allow safety revocation without issuing a new or longer-lived authority."""
    fixed = (
        "schemaVersion",
        "authorityDomain",
        "rootId",
        "rootGeneration",
        "bindingId",
        "journalIdentity",
        "validFrom",
        "expiresAt",
    )
    if any(previous[key] != next_snapshot[key] for key in fixed):
        return False
    old_issuers = {(x["issuerId"], x["issuerGeneration"]): x for x in previous["activeIssuers"]}
    new_issuers = {(x["issuerId"], x["issuerGeneration"]): x for x in next_snapshot["activeIssuers"]}
    if not new_issuers.keys() <= old_issuers.keys() or any(new_issuers[key] != old_issuers[key] for key in new_issuers):
        return False
    old_revoked_issuers = {(x["issuerId"], x["issuerGeneration"]) for x in previous["revokedIssuers"]}
    new_revoked_issuers = {(x["issuerId"], x["issuerGeneration"]) for x in next_snapshot["revokedIssuers"]}
    old_revoked_grants = {(x["issuerId"], x["issuerGeneration"], x["nonce"]) for x in previous["revokedGrants"]}
    new_revoked_grants = {(x["issuerId"], x["issuerGeneration"], x["nonce"]) for x in next_snapshot["revokedGrants"]}
    return old_revoked_issuers < new_revoked_issuers or old_revoked_grants < new_revoked_grants


def install_successor_snapshot(
    db: sqlite3.Connection,
    binding: dict,
    binding_digest: str,
    snapshot: dict,
    operation_id: str,
    expected_epoch: int,
    *,
    revocation_only: bool = False,
) -> dict:
    """Commit a successor under the already qualified root, on the caller's Journal transaction."""
    pin = _loaded_root(db, binding, binding_digest)
    selected_digest = canonical_digest(snapshot)
    selected_bytes = canonical(snapshot)
    if len(selected_bytes.encode("utf-8")) > 1_048_576:
        return {"status": "DENY", "reason": "SNAPSHOT_TOO_LARGE"}
    old = db.execute(
        "SELECT epoch,snapshot_digest,accepted_utc FROM workflow_authority_current WHERE binding_id=?",
        (binding["bindingId"],),
    ).fetchone()
    if old is None:
        raise JournalUnavailable("Initial authority snapshot is absent", write_outcome="NOT_STARTED")
    saved = db.execute(
        "SELECT snapshot_digest,install_operation_id,payload FROM workflow_authority_snapshots "
        "WHERE binding_id=? AND epoch=?",
        (binding["bindingId"], snapshot["epoch"]),
    ).fetchone()
    if saved is not None:
        if (saved["snapshot_digest"], saved["install_operation_id"], saved["payload"]) == (
            selected_digest,
            operation_id,
            selected_bytes,
        ):
            return {"status": "INSTALLED_REPLAY", "snapshotDigest": selected_digest, "nativePermissionGranted": False}
        return {"status": "CONFLICT"}
    if expected_epoch != old["epoch"] or snapshot["epoch"] != old["epoch"] + 1:
        return {"status": "CONFLICT"}
    previous, previous_digest = _snapshot_row(db, binding["bindingId"], old["epoch"])
    if old["snapshot_digest"] != previous_digest or snapshot["previousSnapshotDigest"] != previous_digest:
        raise JournalUnavailable("Broken authority predecessor chain", write_outcome="NOT_STARTED")
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    high = db.execute(
        "SELECT accepted_utc FROM workflow_clock_high_water WHERE journal_identity=?",
        (binding["journalIdentity"],),
    ).fetchone()
    try:
        if high is None or utc_microseconds(now) < max(
            utc_microseconds(high["accepted_utc"]), utc_microseconds(old["accepted_utc"])
        ):
            raise JournalUnavailable("Qualified clock high-water unavailable", write_outcome="NOT_STARTED")
    except LifecycleError as exc:
        raise JournalUnavailable("Invalid clock high-water", write_outcome="NOT_STARTED") from exc
    try:
        verify_signed_authority_snapshot(pin, previous, observed_at=previous["validFrom"])
        verify_signed_authority_snapshot(pin, snapshot, observed_at=now)
    except LifecycleError:
        return {"status": "DENY", "reason": "INVALID_SIGNED_SNAPSHOT"}
    if not _monotonic_successor(previous, snapshot):
        return {"status": "DENY", "reason": "NONMONOTONIC_REVOCATION_OR_ISSUER"}
    if revocation_only and not _revocation_only_successor(previous, snapshot):
        return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE"}
    db.execute(
        "INSERT INTO workflow_authority_snapshots VALUES(?,?,?,?,?,?)",
        (binding["bindingId"], snapshot["epoch"], selected_digest, previous_digest, operation_id, selected_bytes),
    )
    changed = db.execute(
        "UPDATE workflow_authority_current SET epoch=?,snapshot_digest=?,accepted_utc=? "
        "WHERE binding_id=? AND epoch=? AND snapshot_digest=?",
        (snapshot["epoch"], selected_digest, now, binding["bindingId"], old["epoch"], previous_digest),
    ).rowcount
    if changed != 1:
        raise JournalUnavailable("Authority snapshot CAS failed", write_outcome="RECONCILE_REQUIRED")
    db.execute(
        "UPDATE workflow_clock_high_water SET accepted_utc=? WHERE journal_identity=?",
        (now, binding["journalIdentity"]),
    )
    return {"status": "INSTALLED", "snapshotDigest": selected_digest, "nativePermissionGranted": False}
