"""Versioned P01 records for a trusted controller, not a public admission API.

Evidence references are bindings, not authenticity checks. P02/P04/P05 must
establish source coverage, receipt authority and an unavoidable host gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

SCHEMA_VERSION = 1
MAX_INTEGER = (1 << 63) - 1
ROLES = frozenset({"worker", "task_review", "implementation_audit", "final_audit", "coordinator", "closeout"})


def uint(value: int, *, bounded: bool = True) -> int:
    if type(value) is not int or value < 0 or (bounded and value > MAX_INTEGER):
        raise ValueError("Expected an unsigned integer in the supported domain")
    return value


def identity(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Identity must be a nonempty string")
    value.encode("utf-8")  # Reject unpaired surrogates; never normalize identifiers.
    return value


def canonical(value: Any) -> str:
    def check(item: Any) -> None:
        if item is None or type(item) in (bool, int):
            return
        if isinstance(item, str):
            item.encode("utf-8")
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for key, child in item.items():
                check(key)
                check(child)
            return
        raise ValueError("Canonical records allow JSON values without floats")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRef:
    ref: str
    digest: str

    def __post_init__(self) -> None:
        identity(self.ref)
        if not isinstance(self.digest, str) or not re.fullmatch("[0-9a-f]{64}", self.digest):
            raise ValueError("Evidence digest must be lowercase SHA-256")


@dataclass(frozen=True)
class BudgetScope:
    budget_scope_id: str
    run_id: str
    unit_definition_id: str

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            identity(value)


@dataclass(frozen=True)
class BudgetPolicy:
    policy_id: str
    revision: int
    run_cap: int
    task_caps: dict[str, int]
    # Key is a task id, or "" for the run-owned closeout allocation.
    protected_closeout: dict[str, int]
    authorization: EvidenceRef

    def __post_init__(self) -> None:
        identity(self.policy_id)
        for value in (self.revision, self.run_cap, *self.task_caps.values(), *self.protected_closeout.values()):
            uint(value)
        for task in self.task_caps:
            identity(task)
        if any(key != "" and key not in self.task_caps for key in self.protected_closeout):
            raise ValueError("Closeout allocation owner must belong to this run")
        uint(sum(self.protected_closeout.values()))
        if not isinstance(self.authorization, EvidenceRef):
            raise ValueError("Policy authorization reference is required")


@dataclass(frozen=True)
class Operation:
    budget_scope_id: str
    operation_id: str
    dispatch_key: str
    run_id: str
    task_id: str | None
    role: str
    attempt_id: str
    retry_ordinal: int
    attribution_reason: str
    policy_id: str
    policy_revision: int
    route_id: str
    source_id: str
    unit_definition_id: str
    upper_bound_tokens: int
    permit_id: str
    input_digest: str
    route_qualification: EvidenceRef
    issuer: EvidenceRef
    validity: EvidenceRef
    operation_class: str = "ORDINARY"
    closeout_allocation_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "budget_scope_id",
            "operation_id",
            "dispatch_key",
            "run_id",
            "attempt_id",
            "attribution_reason",
            "policy_id",
            "route_id",
            "source_id",
            "unit_definition_id",
            "permit_id",
        ):
            identity(getattr(self, name))
        for value in (self.retry_ordinal, self.policy_revision, self.upper_bound_tokens):
            uint(value)
        if self.task_id is not None:
            identity(self.task_id)
        if self.role not in ROLES:
            raise ValueError("Unsupported role")
        if self.role in {"worker", "task_review", "implementation_audit"} and self.task_id is None:
            raise ValueError("Task work cannot be attributed to run overhead")
        if not re.fullmatch("[0-9a-f]{64}", self.input_digest):
            raise ValueError("Input digest must be SHA-256")
        if not all(
            isinstance(getattr(self, name), EvidenceRef) for name in ("route_qualification", "issuer", "validity")
        ):
            raise ValueError("Operation evidence bindings are required")
        owner = self.task_id if self.task_id is not None else ""
        if self.operation_class == "CLOSEOUT":
            if self.closeout_allocation_id != owner:
                raise ValueError("Closeout must use its own allocation")
        elif self.operation_class != "ORDINARY" or self.closeout_allocation_id is not None:
            raise ValueError("Invalid operation class/allocation")

    @property
    def binding_digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class Permit:
    permit_id: str
    operation_id: str
    binding_digest: str
    status: str
    claim_id: str | None


@dataclass(frozen=True)
class AuthoritativeReceipt:
    receipt_id: str
    budget_scope_id: str
    operation_id: str
    dispatch_key: str
    permit_id: str
    binding_digest: str
    attempt_id: str
    route_id: str
    source_id: str
    source_event_id: str
    source_schema_version: str
    unit_definition_id: str
    reported_tokens: int
    coverage: EvidenceRef
    raw_evidence: EvidenceRef
    attestation: EvidenceRef
    final: bool = True

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name not in {"reported_tokens", "coverage", "raw_evidence", "attestation", "final"}:
                identity(value)
        uint(self.reported_tokens, bounded=False)  # Preserve oversized actual usage.
        if self.final is not True:
            raise ValueError("Streaming observations are not settlement receipts")
        if not re.fullmatch("[0-9a-f]{64}", self.binding_digest):
            raise ValueError("Invalid operation binding digest")
        if not all(
            isinstance(getattr(self, name), EvidenceRef) for name in ("coverage", "raw_evidence", "attestation")
        ):
            raise ValueError("Authoritative receipt references are required")


@dataclass(frozen=True)
class OpeningBalance:
    opening_balance_id: str
    source_id: str
    unit_definition_id: str
    task_spent: dict[str, int | None]
    run_overhead: int | None
    # P01 accepts only proven empty pending or unknown. Nonempty imports belong to P02.
    pending_operations: tuple[()] | None
    cutoff: EvidenceRef
    proof: EvidenceRef
    covered_source_events: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for value in (self.opening_balance_id, self.source_id, self.unit_definition_id):
            identity(value)
        for key, amount in self.task_spent.items():
            identity(key)
            if amount is not None:
                uint(amount)
        if self.run_overhead is not None:
            uint(self.run_overhead)
        if self.pending_operations not in ((), None):
            raise ValueError("Nonempty historical pending import requires P02")
        if not isinstance(self.cutoff, EvidenceRef) or not isinstance(self.proof, EvidenceRef):
            raise ValueError("Opening proof and coverage cutoff are required")
        for source, event in self.covered_source_events:
            identity(source)
            identity(event)


@dataclass(frozen=True)
class Projection:
    scope_key: str
    journal_revision: int
    known_spent: int
    spent: int | None
    active_reservations: int | None
    protected_closeout: int | None
    run_overhead: int | None
    qualification: str
    gate_status: str
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class JournalEvent:
    event_id: str
    budget_scope_id: str
    transaction_id: str
    journal_revision: int
    event_type: str
    payload: dict[str, Any]
    payload_digest: str
    writer: EvidenceRef
    observed_at: str
    schema_version: int = SCHEMA_VERSION
    ordinal: int = 0


# Storage version is separate from interpretation of existing P01 event bytes.
STORAGE_SCHEMA_VERSION = 5
PROTECTED_STORAGE_SCHEMA_VERSION = 6
MAX_INPUT_BYTES = 1 << 20
MAX_IMPORT_BYTES = 4 << 20
MAX_ATOMS = 4096


def bounded_identity(value: str) -> str:
    identity(value)
    if len(value.encode("utf-8")) > 1024:
        raise ValueError("Identity exceeds input bound")
    return value


@dataclass(frozen=True)
class SourceProfile:
    profile_id: str
    budget_scope_id: str
    source_id: str
    schema_version: str
    unit_definition_id: str
    coverage_namespace: str
    counter_mode: str
    qualification_ref: EvidenceRef
    fixture_only: bool = False
    cached_is_subset: bool = True
    reasoning_is_subset: bool = True
    finality_rule: str = "FINAL_WITH_COMPLETE_ATOMS"
    aggregate_rule: str = "COMPLETE_PARTITION"
    order_rule: str = "MONOTONIC_SEQUENCE"
    epoch_rule: str = "EXPLICIT"
    role_mapping: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "profile_id",
            "budget_scope_id",
            "source_id",
            "schema_version",
            "unit_definition_id",
            "coverage_namespace",
        ):
            bounded_identity(getattr(self, name))
        if self.counter_mode not in {"OPERATION_FINAL", "CUMULATIVE"}:
            raise ValueError("Unsupported source counter")
        if (
            self.finality_rule != "FINAL_WITH_COMPLETE_ATOMS"
            or self.aggregate_rule != "COMPLETE_PARTITION"
            or self.order_rule != "MONOTONIC_SEQUENCE"
            or self.epoch_rule != "EXPLICIT"
        ):
            raise ValueError("Unsupported qualified source rules")
        if any(
            type(getattr(self, name)) is not bool
            for name in ("fixture_only", "cached_is_subset", "reasoning_is_subset")
        ):
            raise ValueError("Profile flags must be booleans")
        if not isinstance(self.qualification_ref, EvidenceRef):
            raise ValueError("Controller qualification required")
        if self.fixture_only and not (
            self.source_id.startswith("fixture:")
            and self.coverage_namespace.startswith("fixture:")
            and self.unit_definition_id == "reportedTokens:fixture:v1"
        ):
            raise ValueError("Fixture authority cannot qualify a real domain")
        mapping = dict(self.role_mapping)
        if len(mapping) != len(self.role_mapping) or any(v not in ROLES for v in mapping.values()):
            raise ValueError("Invalid explicit role mapping")
        for key in mapping:
            bounded_identity(key)

    @property
    def profile_digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class CoverageAtom:
    namespace: str
    epoch: str
    atom_id: str
    operation_id: str
    operation_digest: str
    task_id: str | None
    role: str
    amount: int | None
    membership_proof: EvidenceRef

    def __post_init__(self) -> None:
        for name in ("namespace", "epoch", "atom_id", "operation_id", "role"):
            bounded_identity(getattr(self, name))
        if self.task_id is not None:
            bounded_identity(self.task_id)
        if not re.fullmatch("[0-9a-f]{64}", self.operation_digest):
            raise ValueError("Atom operation binding required")
        if self.amount is not None:
            uint(self.amount, bounded=False)
        if not isinstance(self.membership_proof, EvidenceRef):
            raise ValueError("Atom membership proof required")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.namespace, self.epoch, self.atom_id


@dataclass(frozen=True)
class CounterMembership:
    """Qualified position of a paid unit; separate from its financial identity."""

    namespace: str
    epoch: str
    atom_id: str
    start_sequence: int
    end_sequence: int
    proof: EvidenceRef

    def __post_init__(self) -> None:
        for value in (self.namespace, self.epoch, self.atom_id):
            bounded_identity(value)
        uint(self.start_sequence)
        uint(self.end_sequence)
        if self.start_sequence >= self.end_sequence or not isinstance(self.proof, EvidenceRef):
            raise ValueError("Ordered counter interval and qualification proof required")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.namespace, self.epoch, self.atom_id


@dataclass(frozen=True)
class SourceBaseline:
    profile_id: str
    epoch: str
    sequence: int
    total: int
    cutoff_proof: EvidenceRef

    def __post_init__(self) -> None:
        bounded_identity(self.profile_id)
        bounded_identity(self.epoch)
        uint(self.sequence)
        uint(self.total, bounded=False)
        if not isinstance(self.cutoff_proof, EvidenceRef):
            raise ValueError("Baseline origin/cutoff proof required")


@dataclass(frozen=True)
class UsageObservation:
    profile_id: str
    source_event_id: str
    epoch: str
    sequence: int
    kind: str
    total: int | None
    atoms: tuple[CoverageAtom, ...]
    receipts: tuple[AuthoritativeReceipt, ...]
    raw: str
    raw_evidence: EvidenceRef
    components: dict[str, int | None] = field(default_factory=dict)
    interval_memberships: tuple[CounterMembership, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.profile_id, self.source_event_id, self.epoch):
            bounded_identity(value)
        uint(self.sequence)
        if self.kind not in {"FINAL", "SNAPSHOT", "STREAM", "PARENT"}:
            raise ValueError("Unsupported observation kind")
        if self.total is not None:
            uint(self.total, bounded=False)
        if not isinstance(self.raw, str) or len(self.raw.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("Bounded raw evidence required")
        if (
            not isinstance(self.raw_evidence, EvidenceRef)
            or hashlib.sha256(self.raw.encode("utf-8")).hexdigest() != self.raw_evidence.digest
        ):
            raise ValueError("Raw evidence digest mismatch")
        if max(len(self.atoms), len(self.receipts), len(self.interval_memberships)) > MAX_ATOMS:
            raise ValueError("Coverage input bound exceeded")
        if set(self.components) - {"input", "cached", "output", "reasoning"}:
            raise ValueError("Unknown component semantics")
        for amount in self.components.values():
            if amount is not None:
                uint(amount, bounded=False)
        items: tuple[CoverageAtom | AuthoritativeReceipt | CounterMembership, ...] = (
            *self.atoms,
            *self.receipts,
            *self.interval_memberships,
        )
        for item in items:
            item.__post_init__()
        if len(canonical(asdict(self)).encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("Canonical observation exceeds input bound")


@dataclass(frozen=True)
class HistoricalCharge:
    operation: Operation
    receipt: AuthoritativeReceipt
    profile_id: str
    atoms: tuple[CoverageAtom, ...]
    claim_id: str
    dispatch_proof: EvidenceRef


@dataclass(frozen=True)
class PendingImport:
    operation: Operation
    claim_id: str | None
    proof: EvidenceRef
    state: str = "RESERVED"


@dataclass(frozen=True)
class CloseoutLineage:
    policy_id: str
    policy_revision: int
    allocations: dict[str, int]
    completeness_proof: EvidenceRef


@dataclass(frozen=True)
class OpeningImport:
    opening: OpeningBalance
    profiles: tuple[SourceProfile, ...]
    historical: tuple[HistoricalCharge, ...]
    pending: tuple[PendingImport, ...] | None
    baselines: tuple[SourceBaseline, ...] = ()
    unknown_intervals: tuple[EvidenceRef, ...] = ()
    known_partials: dict[str, int] = field(default_factory=dict)
    inventory_proof: EvidenceRef | None = None
    closeout_lineage: CloseoutLineage | None = None


@dataclass(frozen=True)
class ImportAmendment:
    opening_digest: str
    completed_import: OpeningImport
    proof: EvidenceRef


@dataclass(frozen=True)
class UsageOutcome:
    status: str
    revision: int
    detail: str = ""


def utc_instant(value: str) -> datetime:
    """Require an explicit UTC instant; never infer time from local files."""
    if not isinstance(value, str):
        raise ValueError("UTC timestamp required")
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() != timedelta(0):
        raise ValueError("Aware UTC timestamp required")
    return instant


@dataclass(frozen=True)
class RunClosure:
    closure_id: str
    run_id: str
    unit_definition_id: str
    closed_at_utc: str
    scope_revisions: tuple[tuple[str, int], ...]
    final_outcome_ref: EvidenceRef
    accounting_completion_ref: EvidenceRef

    def __post_init__(self) -> None:
        for value in (self.closure_id, self.run_id, self.unit_definition_id):
            bounded_identity(value)
        utc_instant(self.closed_at_utc)
        if not self.scope_revisions or len(self.scope_revisions) > MAX_ATOMS:
            raise ValueError("Bounded nonempty full-run scope inventory required")
        names = []
        for scope, revision in self.scope_revisions:
            bounded_identity(scope)
            uint(revision)
            names.append(scope)
        if names != sorted(set(names)):
            raise ValueError("Unique ordered scope inventory required")
        for ref in (self.final_outcome_ref, self.accounting_completion_ref):
            if not isinstance(ref, EvidenceRef):
                raise ValueError("Final outcome and accounting evidence required")
            ref.__post_init__()


@dataclass(frozen=True)
class ClosureOutcome:
    status: str
    run_id: str
    closure_id: str
    summary_digest: str
    scope_revisions: tuple[tuple[str, int], ...]
    eligible_after: str


@dataclass(frozen=True)
class CleanupOutcome:
    status: str
    run_id: str
    closure_id: str
    summary_digest: str
    scope_revisions: tuple[tuple[str, int], ...]
    eligible_after: str
    deleted_rows: dict[str, int] = field(default_factory=dict)
    logical_status: str = "NOT_COLLECTED"
    physical_status: str = "NOT_REQUESTED"


@dataclass(frozen=True)
class MaintenanceRequest:
    now_utc: str
    journal_identity: str
    work_deadline_utc: str
    candidate_limit: int = 32
    retention_days: int = 30

    def __post_init__(self) -> None:
        now = utc_instant(self.now_utc)
        if utc_instant(self.work_deadline_utc) <= now:
            raise ValueError("Finite future work deadline required")
        bounded_identity(self.journal_identity)
        if type(self.candidate_limit) is not int or not 1 <= self.candidate_limit <= MAX_ATOMS:
            raise ValueError("Bounded maintenance candidate limit required")
        if type(self.retention_days) is not int or self.retention_days != 30:
            raise ValueError("This policy retains details for exactly 30 days")


class JournalUnavailable(RuntimeError):
    """No new dispatch entitlement may be inferred from this error."""

    def __init__(self, message: str, *, write_outcome: str = "RECONCILE_REQUIRED") -> None:
        super().__init__(message)
        self.write_outcome = write_outcome


class RevisionConflict(RuntimeError):
    pass


class _BindingConflict(Exception):
    def __init__(self, detail: str, scopes: tuple[str, ...] = ()) -> None:
        super().__init__(detail)
        self.scopes = scopes


if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from typing import Protocol

    class _FinancialTransactionPort(Protocol):
        """Only the capabilities used by admitted reservation and claim rules."""

        def _require_financial_transaction(self) -> None: ...

        def _reserve_identity_keys(self, operation: Operation) -> None: ...

        def _closed_scope(self, scope: str) -> object | None: ...

        def _conflict(self, scopes: tuple[str, ...], reason: str, payload: dict) -> str: ...

        def _key(self, kind: str, key: object, scope: str, owner: str, value: str) -> bool: ...

        def _load(self, scope: str) -> tuple[dict | None, int]: ...

        def _record(self, scope: str, state: dict | None, revision: int, kind: str, payload: dict) -> int: ...

    class _JournalStoragePort(_FinancialTransactionPort, Protocol):
        """Static view of the existing live Journal composition; no runtime base."""

        _admission_depth: int
        _utc_clock: Callable[[], datetime]

        def _archive_state(self, scope: str, *, restore: bool = False) -> tuple[dict, int]: ...

        @staticmethod
        def _binding_equal(left: dict, right: dict) -> bool: ...

        @staticmethod
        def _binding_scopes(binding: dict) -> set[str]: ...

        def _cancellation_witnesses(self, scope: str, state: dict) -> list[dict]: ...

        def _check_observed(self, candidate: dict) -> None: ...

        def _check_owner(self) -> None: ...

        def _closed_evidence(self, scope: str, evidence: dict) -> str: ...

        def _closed_scope(self, scope: str) -> sqlite3.Row | None: ...

        @staticmethod
        def _closure_outcome(value: dict, status: str) -> ClosureOutcome: ...

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
        ) -> int: ...

        @staticmethod
        def _compile_opening(scope: BudgetScope, policy: BudgetPolicy, value: OpeningImport) -> dict: ...

        @staticmethod
        def _create_v4_schema(db: sqlite3.Connection, *, writer_version: int = 4) -> None: ...

        _database_identity: tuple[int, int] | None

        @property
        def _db(self) -> sqlite3.Connection: ...

        @_db.setter
        def _db(self, value: sqlite3.Connection | None) -> None: ...

        @staticmethod
        def _entry(table: str, key: object, scope: str, owner: str, payload: dict) -> dict: ...

        def _exception_chain(self, run_id: str, *, restore: bool = False) -> list[dict]: ...

        @staticmethod
        def _financial_state(state: dict) -> dict: ...

        @staticmethod
        def _financial_totals(state: dict, revision: int) -> dict: ...

        def _import_entries(self, scope: str, after: dict) -> tuple[list, list]: ...

        def _index(self, table: str, key: str, scope: str, owner: str, payload: dict) -> dict: ...

        def _live_facts(self, scope: str, *, restore: bool = False) -> tuple[dict, int, list, list]: ...

        _observation_scope: str | None

        def _observed_candidates(self, scope: str, evidence: dict) -> list[dict]: ...

        def _observed_lookup(self, namespace: str, key: str) -> dict | None: ...

        _owner: tuple[int, int]
        _path: Path

        def _preflight_supplied_finals(self, scope: str, receipts: list[dict]) -> None: ...

        def _retained(self, table: str, key: str) -> dict | None: ...

        def _source_preflight(self, receipt: dict) -> None: ...

        _storage_version: int

        def _sync_baselines(self, scope: str, state: dict, revision: int) -> None: ...

        def _transaction(self, observation_scope: str | None = None) -> AbstractContextManager[None]: ...

        def _v2_indexes(self, indexes: list, identities: list) -> None: ...

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
        ) -> UsageOutcome: ...

        @classmethod
        def _validate_v2_history(cls, db: sqlite3.Connection, version: int = 2) -> None: ...

        def _write_admission(self) -> AbstractContextManager[None]: ...

        def closed_run(self, run_id: str) -> dict | None: ...

        fault_hook: Callable[[str], None] | None

        @property
        def journal_identity(self) -> str: ...

        writer: EvidenceRef
else:
    # Preserve the exact nominal runtime bases and authority checks.
    _FinancialTransactionPort = object
    _JournalStoragePort = object


class JournalHandle(_JournalStoragePort):
    """Internal type marker for the storage-owning Journal implementation."""


def _projection(state: dict, revision: int) -> Projection:
    tasks = {}
    for task, spent in state["task_spent"].items():
        active = sum(op["reservation"] for op in state["operations"].values() if op["binding"]["task_id"] == task)
        tasks[task] = {
            "known_spent": spent if spent is not None else state.get("known_partials", {}).get(task, 0),
            "spent": spent if state["qualified"] else None,
            "active_reservations": active if state["opening"]["pending_operations"] == [] else None,
            "protected_closeout": state["protected"].get(task, 0),
        }
    known = sum(x["known_spent"] for x in tasks.values()) + (
        state["overhead"] if state["overhead"] is not None else state.get("known_partials", {}).get("", 0)
    )
    active = sum(op["reservation"] for op in state["operations"].values())
    return Projection(
        scope_key=state["scope"]["budget_scope_id"],
        journal_revision=revision,
        known_spent=known,
        spent=known if state["qualified"] else None,
        active_reservations=active if state["opening"]["pending_operations"] == [] else None,
        protected_closeout=(
            sum(state["protected"].values())
            if all(x is not None and x >= 0 for x in state["protected"].values())
            else None
        ),
        run_overhead=state["overhead"],
        qualification="QUALIFIED"
        if state["qualified"]
        else ("CONFLICT" if state["gate"] == "CONFLICT" else "INCOMPLETE"),
        gate_status=state["gate"],
        tasks=tasks,
    )


def _operation(data: dict) -> Operation:
    fields = dict(data)
    for key in ("route_qualification", "issuer", "validity"):
        fields[key] = EvidenceRef(**fields[key])
    return Operation(**fields)


def _refresh_v2(state: dict) -> dict:
    """Recompute qualification without treating unrelated proof as resolution."""
    if state.get("mode") != "COVERAGE_V2":
        return state
    if "unresolved_reasons" not in state or "opening_complete" not in state:
        # No silent promotion of a previously written untyped V2 projection.
        state.setdefault("unresolved_reasons", {})["untyped:legacy"] = {"kind": "UNTYPED_HISTORY"}
        state["opening_complete"] = False
    reasons = state["unresolved_reasons"]
    for key, reason in list(reasons.items()):
        op = state["operations"].get(reason.get("operation_id"))
        if (
            reason["kind"] == "OPERATION_PENDING"
            and op
            and op["state"] in {"SETTLED", "CANCELLED_WITH_NO_DISPATCH_PROOF"}
        ):
            del reasons[key]
    complete = (
        state["opening_complete"]
        and not any(x["kind"] != "OPERATION_PENDING" for x in reasons.values())
        and all(v is not None and v >= 0 for v in state["protected"].values())
    )
    state["qualified"] = bool(complete and state["gate"] != "CONFLICT")
    pending = any(op["state"] == "UNAVAILABLE" for op in state["operations"].values())
    state["input_unavailable"] = bool(reasons or pending or not state["opening_complete"])
    if state["gate"] not in {"CONFLICT", "BOUND_BROKEN", "CLOSED"}:
        state["gate"] = "READY" if complete and not reasons and not pending else "INCOMPLETE"
    return state


def _local_identity(path: Path, *, directory: bool = False) -> tuple[int, int]:
    value = path.lstat()
    reparse = getattr(value, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    valid_type = stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)
    if not valid_type or reparse or not value.st_ino or (not directory and value.st_nlink != 1):
        raise JournalUnavailable("Unsupported local write-admission path", write_outcome="NOT_STARTED")
    return value.st_dev, value.st_ino
