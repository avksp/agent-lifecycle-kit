"""Compile provenance-bound imports without writes, permits or host inference."""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import asdict

from .closing_resource_recovery import _claim_in_transaction, _reserve_in_transaction
from .contracts import (
    MAX_IMPORT_BYTES,
    PROTECTED_STORAGE_SCHEMA_VERSION,
    AuthoritativeReceipt,
    BudgetPolicy,
    BudgetScope,
    CloseoutLineage,
    EvidenceRef,
    OpeningBalance,
    OpeningImport,
    Operation,
    Permit,
    Projection,
    canonical,
    digest,
    identity,
    uint,
)
from .normalization import UsageConflict, UsageUnavailable, semantic_final
from .workflow_store import (
    P02_EVENTS,
    P02_TABLES,
    JournalUnavailable,
    _apply,
    _BindingConflict,
    _event_payload,
    _projection,
)


def _opening_qualification(value, policy, opening, totals, consumed):
    lineage = value.closeout_lineage
    protection_known = not policy.protected_closeout or (
        value.pending is not None
        and isinstance(value.inventory_proof, EvidenceRef)
        and not value.unknown_intervals
        and isinstance(lineage, CloseoutLineage)
        and isinstance(lineage.completeness_proof, EvidenceRef)
        and (lineage.policy_id, lineage.policy_revision, lineage.allocations)
        == (policy.policy_id, policy.revision, policy.protected_closeout)
    )
    protected = {
        key: amount - consumed[key] if protection_known else None for key, amount in policy.protected_closeout.items()
    }
    if any(v is not None and v < 0 for v in protected.values()):
        protection_known = False
    balances = {**opening.task_spent, "": opening.run_overhead}
    known = dict(totals)
    for key, amount in value.known_partials.items():
        uint(amount)
        if key not in balances or balances[key] is not None or amount < totals[key]:
            raise UsageConflict("Invalid known partial subtotal")
        known[key] = amount
    for key, amount in balances.items():
        if amount is not None and amount != totals[key]:
            raise UsageUnavailable("Opening total requires its complete historical charge partition")
    overflow = sum(known.values()) > (1 << 63) - 1
    pending_known = value.pending is not None and isinstance(value.inventory_proof, EvidenceRef)
    complete = (
        all(x is not None for x in balances.values())
        and pending_known
        and protection_known
        and not value.unknown_intervals
        and not overflow
    )
    return protected, balances, known, protection_known, pending_known, complete, overflow


def _opening_baselines(value, profiles):
    baselines, counter_domains = {}, set()
    for baseline in value.baselines:
        baseline.__post_init__()
        if baseline.profile_id not in profiles:
            raise UsageUnavailable("Baseline source is unqualified")
        key = canonical([baseline.profile_id, baseline.epoch])
        if key in baselines:
            raise UsageConflict("Repeated baseline")
        p = profiles[baseline.profile_id]
        domain = (p.source_id, p.coverage_namespace, baseline.epoch, p.unit_definition_id)
        if p.counter_mode != "CUMULATIVE" or domain in counter_domains:
            raise UsageConflict("Baseline requires one profile per qualified counter domain")
        counter_domains.add(domain)
        precutoff = [
            canonical(a.key)
            for h in value.historical
            for a in h.atoms
            if h.operation.source_id == p.source_id
            and a.namespace == p.coverage_namespace
            and a.epoch == baseline.epoch
        ]
        baselines[key] = {
            **asdict(baseline),
            "checkpoints": {str(baseline.sequence): baseline.total},
            "frontier": {"origin_sequence": baseline.sequence, "precutoff_atoms": sorted(precutoff), "members": {}},
        }
    return baselines


def compile_opening(scope: BudgetScope, policy: BudgetPolicy, value: OpeningImport) -> dict:
    scope.__post_init__()
    policy.__post_init__()
    value.opening.__post_init__()
    if len(canonical(asdict(value)).encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Opening import exceeds input bound")
    opening = value.opening
    if opening.unit_definition_id != scope.unit_definition_id or set(opening.task_spent) != set(policy.task_caps):
        raise UsageConflict("Opening scope/task/unit mismatch")
    profiles = {}
    for p in value.profiles:
        p.__post_init__()
        if p.budget_scope_id != scope.budget_scope_id or p.unit_definition_id != scope.unit_definition_id:
            raise UsageConflict("Import profile domain mismatch")
        if p.profile_id in profiles:
            raise UsageConflict("Repeated import profile")
        profiles[p.profile_id] = p
    totals = {key: 0 for key in policy.task_caps}
    totals[""] = 0
    operations, finals, consumed, atoms = {}, {}, {k: 0 for k in policy.protected_closeout}, set()
    bound_broken = False

    def operation(op):
        op.__post_init__()
        if (
            op.budget_scope_id != scope.budget_scope_id
            or op.run_id != scope.run_id
            or op.unit_definition_id != scope.unit_definition_id
            or op.task_id not in (None, *policy.task_caps)
        ):
            raise UsageConflict("Historical operation scope/task/unit mismatch")
        # P02 does not adopt a replacement policy. A future compatible amendment
        # must be qualified explicitly; unknown policy lineage stays unavailable.
        if (op.policy_id, op.policy_revision) != (policy.policy_id, policy.revision):
            raise UsageUnavailable("Historical policy compatibility is unproved")
        if op.operation_id in operations:
            raise UsageConflict("Duplicate historical/pending operation")
        operations[op.operation_id] = {
            "binding": asdict(op),
            "digest": op.binding_digest,
            "state": "RESERVED",
            "claim_id": None,
            "reservation": op.upper_bound_tokens,
            "actual": None,
        }
        if op.operation_class == "CLOSEOUT" and op.closeout_allocation_id not in consumed:
            raise UsageConflict("Unknown original closeout allocation")
        return operations[op.operation_id]

    for charge in value.historical:
        op = charge.operation
        stored = operation(op)
        if not isinstance(charge.dispatch_proof, EvidenceRef) or not charge.claim_id:
            raise UsageUnavailable("Historical dispatch/claim provenance required")
        profile = profiles.get(charge.profile_id)
        if profile is None:
            raise UsageUnavailable("Historical source profile missing")
        semantic = semantic_final(op, charge.receipt, charge.atoms, profile)
        for atom in charge.atoms:
            if atom.key in atoms:
                raise UsageConflict("Overlapping historical coverage")
            atoms.add(atom.key)
        amount = charge.receipt.reported_tokens
        totals[op.task_id or ""] += amount
        stored.update(state="SETTLED", claim_id=charge.claim_id, reservation=0, actual=amount)
        finals[op.operation_id] = {
            "receipt": asdict(charge.receipt),
            "semantics": semantic,
            "atoms": [asdict(a) for a in charge.atoms],
            "profile_id": charge.profile_id,
        }
        if op.operation_class == "CLOSEOUT":
            consumed[op.closeout_allocation_id] += min(op.upper_bound_tokens, amount)
        bound_broken |= amount > op.upper_bound_tokens
    for pending in value.pending or ():
        op = pending.operation
        stored = operation(op)
        if not isinstance(pending.proof, EvidenceRef):
            raise UsageUnavailable("Pending dispatch/no-dispatch proof required")
        if pending.state not in {"RESERVED", "DISPATCHED", "UNAVAILABLE", "CANCELLED_WITH_NO_DISPATCH_PROOF"}:
            raise UsageConflict("Unknown pending operation state")
        if pending.state in {"DISPATCHED", "UNAVAILABLE"} and not pending.claim_id:
            raise UsageUnavailable("Possible historical dispatch requires original claim")
        cancelled = pending.state == "CANCELLED_WITH_NO_DISPATCH_PROOF"
        stored.update(
            claim_id=pending.claim_id,
            state=pending.state if cancelled else ("UNAVAILABLE" if pending.claim_id else "RESERVED"),
            reservation=0 if cancelled else op.upper_bound_tokens,
        )
        if op.operation_class == "CLOSEOUT" and not cancelled:
            consumed[op.closeout_allocation_id] += op.upper_bound_tokens
    protected, balances, known, protection_known, pending_known, complete, overflow = _opening_qualification(
        value, policy, opening, totals, consumed
    )
    task_spent = dict(opening.task_spent)
    baselines = _opening_baselines(value, profiles)
    data = asdict(opening)
    data["pending_operations"] = [] if pending_known else None
    state = {
        "scope": asdict(scope),
        "policy": asdict(policy),
        "opening": data,
        "operations": operations,
        "task_spent": task_spent,
        "overhead": opening.run_overhead,
        "protected": protected,
        "qualified": complete,
        "gate": "BOUND_BROKEN" if bound_broken or overflow else ("READY" if complete else "INCOMPLETE"),
        "mode": "COVERAGE_V2",
        "profiles": {k: asdict(p) for k, p in profiles.items()},
        "baselines": baselines,
        "accepted_finals": finals,
        "aliases": {},
        "known_partials": dict(known),
        "opening_history_known": dict(known),
        "historical_operation_ids": sorted(finals),
        "opening_complete": complete,
        "unresolved_reasons": {},
        "opening_import": asdict(value),
        "opening_import_digest": digest(asdict(value)),
        "input_unavailable": not complete,
    }
    if not complete:
        state["unresolved_reasons"]["opening:incomplete"] = {
            "kind": "OPENING",
            "opening_digest": state["opening_import_digest"],
            "unknown_tasks": [k for k, v in balances.items() if v is None],
            "pending_inventory_known": pending_known,
            "protection_known": protection_known,
            "unknown_intervals": [asdict(x) for x in value.unknown_intervals],
        }
    if overflow:
        state["unresolved_reasons"]["opening:overflow"] = {"kind": "OVERFLOW", "origin": "opening"}
    for owner, op in operations.items():
        if op["state"] == "UNAVAILABLE":
            state["unresolved_reasons"]["pending:" + owner] = {"kind": "OPERATION_PENDING", "operation_id": owner}
    if any(op["state"] == "UNAVAILABLE" for op in operations.values()) and state["gate"] == "READY":
        state["gate"] = "INCOMPLETE"
    return state


def _legacy_open_identity_bindings(
    db: sqlite3.Connection, scope: str, revision: int, payload: dict, state: dict | None,
) -> list[list]:
    """Replay accepted OPEN keys, excluding only its immediate rejected shell."""
    following = db.execute(
        "SELECT * FROM events WHERE scope=? AND revision=?", (scope, revision + 1)
    ).fetchone()
    rejected = False
    if following is not None:
        next_payload = _event_payload(following, revision + 1)
        if following["kind"] == "CONFLICT":
            rejected = canonical(next_payload.get("evidence")) == canonical(payload)
        elif following["kind"] == "INPUT_UNAVAILABLE":
            evidence = next_payload.get("evidence", {}).get("input", {})
            shell = _apply(_apply(copy.deepcopy(state), "OPEN", payload), following["kind"], next_payload)
            if "opening" in evidence and shell.get("mode") != "COVERAGE_V2" and shell.get("gate") == "INCOMPLETE":
                opening = copy.deepcopy(evidence["opening"])
                opening["pending_operations"] = None
                rejected = canonical({
                    "scope": shell["scope"], "policy": shell["policy"], "opening": opening,
                }) == canonical(payload)
    if rejected:
        return []
    opening = payload["opening"]
    declarations = [[
        "opening", [scope, opening["opening_balance_id"]], scope,
        opening["opening_balance_id"], digest(payload),
    ]]
    declarations.extend(
        ["source", [source, event], scope, "opening:" + opening["opening_balance_id"], digest(payload)]
        for source, event in opening["covered_source_events"]
    )
    return declarations


def _public_closing_route_fenced(journal, scope: str, run_id: str, operation_id: str, operation_class: str) -> bool:
    """A legacy financial port cannot grant an adopted v6 closing invocation."""
    if journal._storage_version != PROTECTED_STORAGE_SCHEMA_VERSION:
        return False
    if type(run_id) is not str or type(operation_class) is not str:
        return True
    db = journal._db
    if db.execute(
        "SELECT 1 FROM closing_operation_bindings WHERE budget_scope_id=? AND operation_id=?",
        (scope, operation_id),
    ).fetchone() is not None:
        return True
    if db.execute(
        "SELECT 1 FROM closing_policy_effects WHERE run_id=? LIMIT 1", (run_id,)
    ).fetchone() is not None:
        return True
    if operation_class != "CLOSEOUT":
        return False
    return db.execute(
        "SELECT 1 FROM workflow_bindings WHERE run_id=? LIMIT 1", (run_id,)
    ).fetchone() is not None


class JournalAdmissionMixin:
    def open_scope(self, scope: BudgetScope, policy: BudgetPolicy, opening: OpeningBalance) -> str:
        # Frozen records can contain mutable mappings: revalidate at the write boundary.
        scope.__post_init__()
        policy.__post_init__()
        opening.__post_init__()
        if opening.unit_definition_id != scope.unit_definition_id:
            raise ValueError("Opening unit does not match scope")
        if set(opening.task_spent) != set(policy.task_caps):
            raise ValueError("Every task requires an explicit opening balance and cap")
        known = sum(x or 0 for x in opening.task_spent.values()) + (opening.run_overhead or 0)
        uint(known)
        payload = canonical({"scope": asdict(scope), "policy": asdict(policy), "opening": asdict(opening)})
        data = json.loads(payload)
        with self._transaction():
            if self._retained("run_closures", scope.run_id):
                return "CLOSED"
            existing, revision = self._load(scope.budget_scope_id)
            if existing is not None:
                original = {"scope": existing["scope"], "policy": existing["policy"], "opening": existing["opening"]}
                if original == data:
                    return "ALREADY_OPEN"
                return self._conflict((scope.budget_scope_id,), "Opening identity/content mismatch", data)
            try:
                # No partial identity inserts may survive a conflicting batch.
                self._db.execute("SAVEPOINT identity_batch")
                self._key(
                    "opening",
                    [scope.budget_scope_id, opening.opening_balance_id],
                    scope.budget_scope_id,
                    opening.opening_balance_id,
                    digest(data),
                )
                for source, event in opening.covered_source_events:
                    self._key(
                        "source",
                        [source, event],
                        scope.budget_scope_id,
                        "opening:" + opening.opening_balance_id,
                        digest(data),
                    )
                self._db.execute("RELEASE identity_batch")
            except _BindingConflict as exc:
                self._db.execute("ROLLBACK TO identity_batch")
                self._db.execute("RELEASE identity_batch")
                self._record(scope.budget_scope_id, None, 0, "OPEN", data)
                return self._conflict(exc.scopes, str(exc), data)
            self._record(scope.budget_scope_id, None, revision, "OPEN", data)
            return "OPENED"

    def reserve(self, operation: Operation, *, expected_revision: int | None = None) -> str:
        """Record an already-authorized reservation; external trust checks are required."""
        operation.__post_init__()
        with self._transaction():
            if _public_closing_route_fenced(
                self, operation.budget_scope_id, operation.run_id,
                operation.operation_id, operation.operation_class,
            ):
                return "DENY"
            return _reserve_in_transaction(self, operation, expected_revision=expected_revision)

    def claim(self, scope: str, operation_id: str, binding_digest: str, claim_id: str) -> str:
        identity(claim_id)
        with self._transaction():
            if self._storage_version == PROTECTED_STORAGE_SCHEMA_VERSION:
                state, _ = self._load(scope)
                native = state.get("operations", {}).get(operation_id) if state is not None else None
                if native is not None:
                    binding = native.get("binding")
                    if type(binding) is not dict or _public_closing_route_fenced(
                        self, scope, binding.get("run_id"), operation_id,
                        binding.get("operation_class"),
                    ):
                        return "DENY"
            return _claim_in_transaction(self, scope, operation_id, binding_digest, claim_id)

    def note_dispatch(self, scope: str, operation_id: str, proof: EvidenceRef) -> str:
        return self._note(scope, operation_id, "DISPATCH", proof)

    def note_unavailable(self, scope: str, operation_id: str, proof: EvidenceRef) -> str:
        return self._note(scope, operation_id, "UNAVAILABLE", proof)

    def _note(self, scope: str, operation_id: str, kind: str, proof: EvidenceRef) -> str:
        if not isinstance(proof, EvidenceRef):
            raise ValueError("Evidence reference required")
        with self._transaction():
            closed = self._closed_scope(scope)
            if closed:
                return "CLOSED"
            state, revision = self._load(scope)
            if state is None or operation_id not in state["operations"]:
                return "UNAVAILABLE"
            op = state["operations"][operation_id]
            if op["state"] in {"SETTLED", "CANCELLED_WITH_NO_DISPATCH_PROOF"} or not op["claim_id"]:
                return "DENY"
            target = "DISPATCHED" if kind == "DISPATCH" else "UNAVAILABLE"
            if op["state"] == target:
                return "ALREADY_RECORDED"
            self._record(scope, state, revision, kind, {"operation_id": operation_id, "proof": asdict(proof)})
            return "RECORDED"

    def cancel_without_dispatch(self, scope: str, operation_id: str, proof: EvidenceRef) -> str:
        """Caller must supply authoritative definitive no-dispatch/no-charge proof."""
        if not isinstance(proof, EvidenceRef):
            raise ValueError("No-dispatch evidence required")
        with self._transaction():
            closed = self._closed_scope(scope)
            if closed:
                return "CLOSED"
            state, revision = self._load(scope)
            if state is None or operation_id not in state["operations"]:
                return "UNAVAILABLE"
            op = state["operations"][operation_id]
            if op["state"] == "CANCELLED_WITH_NO_DISPATCH_PROOF":
                return "ALREADY_CANCELLED"
            if op["state"] not in {"RESERVED", "UNAVAILABLE"}:
                return "DENY"
            self._record(scope, state, revision, "CANCEL", {"operation_id": operation_id, "proof": asdict(proof)})
            return "CANCELLED"

    def record_settlement(self, receipt: AuthoritativeReceipt) -> str:
        """Record a P04-verified receipt; this does not verify provider authenticity."""
        data = asdict(receipt)
        scope = receipt.budget_scope_id
        receipt.__post_init__()
        with self._transaction(scope):
            if self._closed_scope(scope):
                return self._closed_evidence(scope, data)
            try:
                self._source_preflight(data)
            except _BindingConflict as exc:
                return self._conflict(exc.scopes, str(exc), data)
            state, revision = self._load(scope)
            if state is not None and state.get("mode") == "COVERAGE_V2":
                alias = state.get("aliases", {}).get(canonical([receipt.source_id, receipt.source_event_id]))
                first = state.get("accepted_finals", {}).get(receipt.operation_id)
                if alias and alias["incoming_receipt_digest"] == digest(data):
                    return "ALREADY_CORROBORATED"
                if first and digest(first["receipt"]) == digest(data):
                    return "ALREADY_SETTLED"
                return self._v2_unavailable(
                    scope,
                    state,
                    revision,
                    "Legacy final lacks structured qualified coverage",
                    data,
                    reason_kind="OPERATION_PENDING",
                ).status
            if state is None or receipt.operation_id not in state["operations"]:
                return "UNAVAILABLE"
            op = state["operations"][receipt.operation_id]
            binding = op["binding"]
            keys = ("dispatch_key", "permit_id", "attempt_id", "route_id", "source_id", "unit_definition_id")
            if receipt.binding_digest != op["digest"] or any(data[key] != binding[key] for key in keys):
                return self._conflict((scope,), "Receipt binding mismatch", data)
            if not op["claim_id"] or op["state"] == "CANCELLED_WITH_NO_DISPATCH_PROOF":
                return self._conflict((scope,), "Charge contradicts dispatch history", data)
            self._db.execute("SAVEPOINT identity_batch")
            try:
                receipt_digest = digest(data)
                fresh = self._key(
                    "settlement", [scope, receipt.operation_id], scope, receipt.operation_id, receipt_digest
                )
                self._key(
                    "source", [receipt.source_id, receipt.source_event_id], scope, receipt.operation_id, receipt_digest
                )
                self._db.execute("RELEASE identity_batch")
            except _BindingConflict as exc:
                self._db.execute("ROLLBACK TO identity_batch")
                self._db.execute("RELEASE identity_batch")
                return self._conflict(exc.scopes, str(exc), data)
            if not fresh:
                return "ALREADY_SETTLED" if op["state"] == "SETTLED" else "UNAVAILABLE"
            payload = {"operation_id": receipt.operation_id, "receipt": data}
            try:
                uint(receipt.reported_tokens)
                uint(_projection(state, revision).known_spent + receipt.reported_tokens)
            except ValueError:
                self._record(scope, state, revision, "OVERFLOW", payload)
                return "UNAVAILABLE"
            self._record(scope, state, revision, "SETTLE", payload)
            return "SETTLED_BOUND_BROKEN" if receipt.reported_tokens > binding["upper_bound_tokens"] else "SETTLED"

    def snapshot(self, scope: str) -> Projection:
        self._check_owner()
        state, revision = self._load(scope)
        if state is None:
            raise KeyError(scope)
        closed = self._closed_scope(scope)
        if closed and self._exception_chain(closed["run_id"]):
            state = copy.deepcopy(state)
            state["qualified"] = False
        return _projection(state, revision)

    def permit(self, scope: str, operation_id: str) -> Permit:
        self._check_owner()
        state, _ = self._load(scope)
        if state is None:
            raise KeyError(scope)
        op = state["operations"][operation_id]
        status = (
            "REVOKED"
            if self._closed_scope(scope) or op["state"] == "CANCELLED_WITH_NO_DISPATCH_PROOF"
            else ("CLAIMED" if op["claim_id"] is not None else "ISSUED")
        )
        return Permit(op["binding"]["permit_id"], operation_id, op["digest"], status, op["claim_id"])

    def rebuild(self, scope: str) -> Projection:
        """Rebuild projection from immutable events; no implicit host redispatch."""
        with self._transaction():
            closed = self._closed_scope(scope)
            if closed:
                if self._retained("cleanup_receipts", closed["run_id"]):
                    self._archive_state(scope, restore=True)
                else:
                    state, revision, _, _ = self._live_facts(scope, restore=True)
                    value = self.closed_run(closed["run_id"])
                    if digest(self._financial_state(state)) != value["summary"]["scopes"][scope]["financial_digest"]:
                        raise JournalUnavailable("Closed replay differs from closure seal")
                    self._db.execute(
                        "INSERT INTO scope_state VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                        (scope, revision, canonical(state)),
                    )
                    self._exception_chain(closed["run_id"], restore=True)
                return self.snapshot(scope)
            rows = self._db.execute("SELECT * FROM events WHERE scope=? ORDER BY revision,ordinal", (scope,)).fetchall()
            if not rows:
                raise KeyError(scope)
            state = None
            for revision, row in enumerate(rows, 1):
                payload = _event_payload(row, revision)
                if row["kind"] in P02_EVENTS:
                    try:
                        self._v2_indexes(payload.get("indexes", []), payload.get("identities", []))
                    except _BindingConflict as exc:
                        raise JournalUnavailable("Immutable replay index conflict") from exc
                state = _apply(state, row["kind"], payload, revision=revision - 1)
            self._db.execute(
                "INSERT INTO scope_state VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                (scope, len(rows), canonical(state)),
            )
            expected_indexes = {table: set() for table in P02_TABLES}
            for row in rows:
                if row["kind"] in P02_EVENTS:
                    for item in json.loads(row["payload"]).get("indexes", []):
                        expected_indexes[item["table"]].add(item["key"])
            for table, expected in expected_indexes.items():
                actual = {row[0] for row in self._db.execute(f"SELECT key FROM {table} WHERE scope=?", (scope,))}
                if actual != expected:
                    raise JournalUnavailable("Immutable index contains facts absent from journal")
            self._sync_baselines(scope, state, len(rows))
            revision = len(rows)
            # An explicit recovery cannot infer that a durable claim was never sent.
            # Keep the reservation and close admission until host evidence resolves it.
            for operation_id, op in sorted(state["operations"].items()):
                if op["claim_id"] is not None and op["state"] in {"RESERVED", "DISPATCHED"}:
                    revision = self._record(
                        scope,
                        state,
                        revision,
                        "UNAVAILABLE",
                        {"operation_id": operation_id, "reason": "Recovery requires authoritative host outcome"},
                    )
            return _projection(state, revision)

    @classmethod
    def _validate_v2_history(cls, db: sqlite3.Connection, version: int = 2) -> None:
        """Read-only legacy replay. Public rebuild intentionally has recovery effects."""
        states, revisions = {}, {}
        expected_indexes = {table: set() for table in P02_TABLES}
        for row in db.execute("SELECT * FROM events ORDER BY scope,revision,ordinal"):
            scope = row["scope"]
            revision = revisions.get(scope, 0) + 1
            payload = _event_payload(row, revision)
            identity_bindings = []
            if row["kind"] in P02_EVENTS:
                if version == 2 and ("after" not in payload or "state_delta" in payload):
                    raise JournalUnavailable("Expected legacy v2 state image")
                for item in payload["indexes"]:
                    if set(item) != {"table", "key", "scope", "owner", "payload"} or item["table"] not in P02_TABLES:
                        raise JournalUnavailable("Malformed legacy index declaration")
                    table, key = item["table"], item["key"]
                    actual = db.execute(f"SELECT * FROM {table} WHERE key=?", (key,)).fetchone()
                    expected = (key, item["scope"], item["owner"], digest(item["payload"]), canonical(item["payload"]))
                    if item["scope"] != scope or actual is None or tuple(actual) != expected:
                        raise JournalUnavailable("Legacy immutable index mismatch")
                    expected_indexes[table].add(key)
                identity_bindings = payload["identities"]
            elif row["kind"] == "RESERVE":
                op = payload["operation"]
                identity_bindings = [
                    [kind, key, scope, op["operation_id"], digest(op)]
                    for kind, key in (
                        ("operation", [scope, op["operation_id"]]),
                        ("dispatch", [scope, op["dispatch_key"]]),
                        ("permit", op["permit_id"]),
                    )
                ]
            elif row["kind"] == "CLAIM":
                # Use pre-event state: CLAIM itself changes this operation's claim_id.
                op = states[scope]["operations"][payload["operation_id"]]
                identity_bindings = [
                    ["claim", op["binding"]["permit_id"], scope, payload["operation_id"], digest(payload["claim_id"])]
                ]
            elif row["kind"] in ("SETTLE", "OVERFLOW"):
                receipt = payload["receipt"]
                identity_bindings = [
                    [kind, key, scope, payload["operation_id"], digest(receipt)]
                    for kind, key in (
                        ("settlement", [scope, payload["operation_id"]]),
                        ("source", [receipt["source_id"], receipt["source_event_id"]]),
                    )
                ]
            elif row["kind"] == "OPEN":
                identity_bindings = _legacy_open_identity_bindings(
                    db, scope, revision, payload, states.get(scope),
                )
            for item in identity_bindings:
                if not isinstance(item, list) or len(item) != 5:
                    raise JournalUnavailable("Malformed legacy identity declaration")
                kind, key, owner_scope, owner, checksum = item
                actual = db.execute(
                    "SELECT * FROM identities WHERE kind=? AND key=?", (kind, canonical(key))
                ).fetchone()
                if actual is None or tuple(actual) != (kind, canonical(key), owner_scope, owner, checksum):
                    raise JournalUnavailable("Legacy identity binding mismatch")
            states[scope] = _apply(states.get(scope), row["kind"], payload, revision=revision - 1)
            revisions[scope] = revision
        projections = {row["scope"]: row for row in db.execute("SELECT * FROM scope_state")}
        if projections.keys() != states.keys():
            raise JournalUnavailable("Legacy projection scope mismatch")
        for scope, state in states.items():
            projection = projections[scope]
            if projection["revision"] != revisions[scope] or canonical(json.loads(projection["data"])) != canonical(
                state
            ):
                raise JournalUnavailable("Legacy projection does not match replay")
        for table, keys in expected_indexes.items():
            if {row[0] for row in db.execute(f"SELECT key FROM {table}")} != keys:
                raise JournalUnavailable("Legacy index contains undeclared facts")
        expected_baselines = {
            (scope, key): value for scope, state in states.items() for key, value in state.get("baselines", {}).items()
        }
        actual_baselines = {(row["scope"], row["key"]): row for row in db.execute("SELECT * FROM source_baselines")}
        if actual_baselines.keys() != expected_baselines.keys():
            raise JournalUnavailable("Legacy source baseline inventory mismatch")
        for (scope, key), expected in expected_baselines.items():
            row = actual_baselines[scope, key]
            # Ordinary P01 reserve/claim events do not rewrite source baselines.
            if not 1 <= row["revision"] <= revisions[scope] or canonical(json.loads(row["data"])) != canonical(
                expected
            ):
                raise JournalUnavailable("Legacy source baseline mismatch")

    @staticmethod
    def _financial_state(state: dict) -> dict:
        # No opening_import, observation input bodies, rejected envelopes or event history.
        fields = (
            "scope",
            "policy",
            "opening",
            "mode",
            "operations",
            "task_spent",
            "overhead",
            "protected",
            "qualified",
            "gate",
            "accepted_finals",
            "aliases",
            "baselines",
            "opening_complete",
            "opening_import_digest",
            "opening_history_known",
            "historical_operation_ids",
            "closure_id",
            "original_gate",
        )
        compact = {k: copy.deepcopy(state[k]) for k in fields if k in state}
        compact["profiles"] = {
            key: {
                k: p[k]
                for k in ("profile_id", "source_id", "schema_version", "unit_definition_id", "qualification_ref")
            }
            for key, p in state.get("profiles", {}).items()
        }
        compact["profile_digests"] = {k: digest(p) for k, p in state.get("profiles", {}).items()}
        compact["unresolved_reasons"] = {}
        return compact

    def _cancellation_witnesses(self, scope: str, state: dict) -> list[dict]:
        """Retain the first accepted proof, including opening evidence completion."""
        witnesses = {}
        for row in self._db.execute(
            "SELECT kind,payload,digest,revision FROM events WHERE scope=? "
            "AND kind IN ('CANCEL','IMPORT_OPENING','IMPORT_EVIDENCE_COMPLETED') ORDER BY revision",
            (scope,),
        ):
            payload = json.loads(row["payload"])
            if row["kind"] == "CANCEL":
                owner = payload["operation_id"]
                if owner in witnesses:
                    raise JournalUnavailable("Repeated cancellation declaration")
                witnesses[owner] = {"operation_id": owner, "proof": payload["proof"], "event_digest": row["digest"]}
                continue
            evidence = payload["evidence"]
            value = evidence if row["kind"] == "IMPORT_OPENING" else evidence["completed_import"]
            opening_digest = digest(value) if row["kind"] == "IMPORT_OPENING" else evidence["opening_digest"]
            if opening_digest != state["opening_import_digest"]:
                raise JournalUnavailable("Cancellation opening lineage mismatch")
            for item in value["pending"] or []:
                if item["state"] != "CANCELLED_WITH_NO_DISPATCH_PROOF":
                    continue
                owner = item["operation"]["operation_id"]
                op = state["operations"].get(owner)
                if (
                    op is None
                    or op["state"] != item["state"]
                    or op["binding"] != item["operation"]
                    or op["digest"] != digest(item["operation"])
                    or op["claim_id"] != item["claim_id"]
                ):
                    raise JournalUnavailable("Imported cancellation binding mismatch")
                EvidenceRef(**item["proof"]).__post_init__()
                declaration_digest = digest(item)
                if owner in witnesses:
                    if witnesses[owner].get("declaration_digest") != declaration_digest:
                        raise JournalUnavailable("Imported cancellation declaration changed")
                    continue
                witnesses[owner] = {
                    "operation_id": owner,
                    "proof": item["proof"],
                    "event_digest": row["digest"],
                    "event_kind": row["kind"],
                    "event_revision": row["revision"],
                    "declaration_digest": declaration_digest,
                    "opening_digest": opening_digest,
                    "import_digest": digest(value),
                    "evidence_digest": digest(evidence),
                }
        return [witnesses[owner] for owner in sorted(witnesses)]
