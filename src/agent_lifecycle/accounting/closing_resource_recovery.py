"""Closing resource reconstruction and private financial transaction primitives.

The reconstruction is diagnostic. The private primitives only mutate an already
admitted Journal transaction; neither authenticates a host nor authorizes a call.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.canonical import load_json_object
from agent_lifecycle.contracts.closing_resource_schemas import (
    validate_closing_operation_binding,
    validate_limit_proposal,
)
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path
from agent_lifecycle.contracts.workflow_state_schemas import _closing_instant

from .closing_resource_policy import classify_current_claim_data
from .contracts import (
    MAX_INTEGER,
    ROLES,
    JournalUnavailable,
    Operation,
    RevisionConflict,
    _BindingConflict,
    _operation,
    _projection,
    canonical,
    digest,
    identity,
    uint,
)
from .workflow_authority_store import _load_run_output_anchor_data


def _require_financial_transaction(journal) -> None:
    journal._check_owner()
    if not journal._db.in_transaction or journal._admission_depth != 1:
        raise JournalUnavailable("Financial operation requires admitted transaction", write_outcome="NOT_STARTED")


def _reserve_in_transaction(journal, operation: Operation, *, expected_revision: int | None = None) -> str:
    """Apply ordinary reservation arithmetic inside the caller's admitted transaction."""
    _require_financial_transaction(journal)
    operation.__post_init__()
    op = asdict(operation)
    scope = operation.budget_scope_id
    if journal._closed_scope(scope):
        return "CLOSED"
    state, revision = journal._load(scope)
    if state is None:
        return "UNAVAILABLE"
    old = state["operations"].get(operation.operation_id)
    if old:
        return (
            "ALREADY_RESERVED"
            if old["digest"] == operation.binding_digest
            else journal._conflict((scope,), "Operation binding changed", op)
        )
    if expected_revision is not None:
        uint(expected_revision)
        if expected_revision != revision:
            raise RevisionConflict("Stale journal revision")
    if state["gate"] != "READY":
        return "UNAVAILABLE"
    policy, binding = state["policy"], state["scope"]
    if (
        operation.run_id != binding["run_id"]
        or operation.unit_definition_id != binding["unit_definition_id"]
        or operation.policy_id != policy["policy_id"]
        or operation.policy_revision != policy["revision"]
        or operation.task_id not in (None, *policy["task_caps"])
    ):
        return journal._conflict((scope,), "Scope/policy/task binding mismatch", op)
    projected = asdict(_projection(state, revision))
    owner = operation.task_id if operation.task_id is not None else ""
    upper = operation.upper_bound_tokens
    transfer = upper if operation.operation_class == "CLOSEOUT" else 0
    if transfer and state["protected"].get(owner, 0) < transfer:
        return "DENY"
    checks = [
        (
            projected["spent"],
            projected["active_reservations"],
            projected["protected_closeout"],
            policy["run_cap"],
        )
    ]
    if operation.task_id is not None:
        task = projected["tasks"][operation.task_id]
        checks.append(
            (
                task["spent"],
                task["active_reservations"],
                task["protected_closeout"],
                policy["task_caps"][operation.task_id],
            )
        )
    for spent, active, protected, cap in checks:
        total = uint(spent + active + upper + protected - transfer)
        if total > cap:
            return "DENY"
    journal._db.execute("SAVEPOINT identity_batch")
    try:
        for kind, key in (
            ("operation", [scope, operation.operation_id]),
            ("dispatch", [scope, operation.dispatch_key]),
            ("permit", operation.permit_id),
        ):
            journal._key(kind, key, scope, operation.operation_id, operation.binding_digest)
        journal._db.execute("RELEASE identity_batch")
    except _BindingConflict as exc:
        journal._db.execute("ROLLBACK TO identity_batch")
        journal._db.execute("RELEASE identity_batch")
        return journal._conflict(exc.scopes, str(exc), op)
    journal._record(scope, state, revision, "RESERVE", {"operation": op})
    return "RESERVED"


def _claim_in_transaction(journal, scope: str, operation_id: str, binding_digest: str, claim_id: str) -> str:
    """Claim once inside the caller's admitted transaction; no dispatch authority is conferred."""
    _require_financial_transaction(journal)
    identity(claim_id)
    if journal._closed_scope(scope):
        return "CLOSED"
    state, revision = journal._load(scope)
    if state is None or operation_id not in state["operations"]:
        return "UNAVAILABLE"
    op = state["operations"][operation_id]
    if binding_digest != op["digest"]:
        return journal._conflict((scope,), "Claim binding mismatch", {"operation_id": operation_id})
    if op["claim_id"] is not None:
        return "ALREADY_CLAIMED"
    if state["gate"] != "READY" or op["state"] != "RESERVED":
        return "DENY"
    journal._key("claim", op["binding"]["permit_id"], scope, operation_id, digest(claim_id))
    journal._record(scope, state, revision, "CLAIM", {"operation_id": operation_id, "claim_id": claim_id})
    return "CLAIM_GRANTED"


def _unavailable(detail: str) -> None:
    raise LifecycleError("closing-resource-recovery-unavailable", detail)


def _resolve_native_operation_data(root: Path, sidecar: dict) -> Operation:
    """Resolve original financial data only; no window or dispatch authority follows."""
    validate_closing_operation_binding(sidecar)
    ref = sidecar["nativeOperationRef"]
    relative = normalize_repo_path(ref["path"], label="native operation")
    try:
        raw = read_authority_bytes(Path(root).absolute() / relative, root=Path(root).absolute(), max_bytes=1_048_576)
        if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            _unavailable("Native operation artifact identity differs")
        operation = _operation(load_json_object(raw, label="native operation"))
    except (LifecycleError, OSError, TypeError, ValueError, KeyError, AttributeError) as exc:
        raise LifecycleError("closing-resource-recovery-unavailable", "Native operation data is unavailable") from exc
    owner = {"scopeKind": "TASK" if operation.task_id is not None else "RUN", "taskId": operation.task_id}
    if (
        operation.binding_digest != sidecar["nativeOperationDigest"]
        or operation.run_id != sidecar["runId"]
        or operation.budget_scope_id != sidecar["budgetScopeId"]
        or operation.operation_id != sidecar["operationId"]
        or operation.unit_definition_id != sidecar["unit"]["unitDefinitionId"]
        or operation.upper_bound_tokens != sidecar["upperBound"]
        or owner != sidecar["owner"]
    ):
        _unavailable("Native operation and closing sidecar differ")
    return operation


def _resolve_pinned_native_operation_data(
    journal, binding: dict, binding_digest: str, sidecar: dict,
) -> dict:
    """Join v6 anchor and original Operation in one admitted transaction; no grant."""
    _require_financial_transaction(journal)
    validate_closing_operation_binding(sidecar)
    if any(sidecar[field] != binding[field] for field in ("bindingId", "runId", "budgetScopeId")):
        _unavailable("Closing operation differs from pinned workflow binding")
    anchor = _load_run_output_anchor_data(journal._db, binding, binding_digest)
    output_root = normalize_repo_path(anchor["runOutputRootRelativePath"], label="run output root")
    operation_path = normalize_repo_path(sidecar["nativeOperationRef"]["path"], label="native operation")
    if operation_path == output_root or not is_under_repo_path(operation_path, output_root):
        _unavailable("Original Operation is outside pinned run output root")
    operation = _resolve_native_operation_data(Path(anchor["artifactAuthorityRootPath"]), sidecar)
    return {
        "anchor": anchor, "operation": operation, "nativeOperationDigest": operation.binding_digest,
        "rootQualificationVerified": False, "financialAdmission": False,
    }


def _owner_key(value: Any) -> str:
    if type(value) is not dict or set(value) != {"scopeKind", "taskId"}:
        _unavailable("Closing owner is malformed")
    kind, task = value["scopeKind"], value["taskId"]
    if kind == "RUN" and task is None:
        return ""
    if kind == "TASK" and type(task) is str and 1 <= len(task) <= 256:
        return task
    _unavailable("Closing owner attribution is malformed")


def _amount(value: Any, label: str) -> int:
    try:
        return uint(value)
    except ValueError:
        _unavailable(f"{label} is unknown or outside the supported domain")


def _sum(values: list[int], label: str) -> int:
    result = sum(values)
    if result > MAX_INTEGER:
        _unavailable(f"{label} overflows the supported domain")
    return result


_SIDECAR_FIELDS = frozenset({
    "schemaVersion", "bindingId", "runId", "budgetScopeId", "closingWindowId",
    "policyEffectDigest", "operationId", "nativeOperationRef", "nativeOperationDigest",
    "action", "owner", "unit", "upperBound", "expectedJournalRevision",
    "expectedWorkflowRevision", "expectedAuthorityEpoch", "expectedGuardStateDigest",
})


def _window_operations(
    state: dict, proposal: dict, bindings: list[dict], effect_digest: str,
) -> dict[str, dict[str, int]]:
    """Join immutable sidecars to original native operation identities once."""
    window = proposal["closingWindowId"]
    operations = state.get("operations")
    if type(operations) is not dict:
        _unavailable("Native operation inventory is unavailable")
    totals: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    for item in bindings:
        if type(item) is not dict or set(item) != _SIDECAR_FIELDS or (
            item.get("schemaVersion") != "agent-closing-operation-binding.v1"
        ):
            _unavailable("Closing operation sidecar is malformed")
        operation_id = item.get("operationId")
        if type(operation_id) is not str or operation_id in seen or operation_id not in operations:
            _unavailable("Closing operation is duplicated or absent from native accounting")
        seen.add(operation_id)
        if item.get("closingWindowId") != window:
            _unavailable("Closing operation belongs to another window")
        if (
            item.get("runId") != proposal["runId"]
            or item.get("budgetScopeId") != proposal["budgetScopeId"]
            or item.get("bindingId") != proposal["bindingId"]
            or item.get("policyEffectDigest") != effect_digest
            or item.get("unit") != proposal["unit"]
        ):
            _unavailable("Closing operation differs from the signed scope")
        for revision_name in ("expectedJournalRevision", "expectedWorkflowRevision", "expectedAuthorityEpoch"):
            if _amount(item[revision_name], revision_name) > (1 << 53) - 1:
                _unavailable("Closing operation revision exceeds the safe-integer domain")
        if type(item["expectedGuardStateDigest"]) is not str or re.fullmatch(
            r"[0-9a-f]{64}", item["expectedGuardStateDigest"]
        ) is None:
            _unavailable("Closing guard identity is malformed")
        owner = _owner_key(item.get("owner"))
        native = operations[operation_id]
        binding = native.get("binding")
        if type(binding) is not dict or native.get("digest") != digest(binding):
            _unavailable("Native operation binding is corrupted")
        if (
            item.get("nativeOperationDigest") != native["digest"]
            or binding.get("operation_id") != operation_id
            or binding.get("budget_scope_id") != proposal["budgetScopeId"]
            or binding.get("run_id") != proposal["runId"]
            or (binding.get("task_id") or "") != owner
            or binding.get("unit_definition_id") != proposal["unit"]["unitDefinitionId"]
            or binding.get("upper_bound_tokens") != item.get("upperBound")
        ):
            _unavailable("Closing sidecar does not match the native operation")
        upper = _amount(item["upperBound"], "operation upper bound")
        reserved = _amount(native.get("reservation"), "native reservation")
        if reserved not in {0, upper}:
            _unavailable("Native reservation has an unsupported partial value")
        actual = native.get("actual")
        if actual is not None:
            _amount(actual, "native actual")
        native_status = native.get("state")
        if native_status not in {
            "RESERVED", "DISPATCHED", "UNAVAILABLE", "SETTLED", "CANCELLED_WITH_NO_DISPATCH_PROOF"
        }:
            _unavailable("Native operation state is unsupported")
        if (native_status == "SETTLED") != (actual is not None):
            _unavailable("Native settlement state and actual differ")
        if native_status in {"SETTLED", "CANCELLED_WITH_NO_DISPATCH_PROOF"} and reserved != 0:
            _unavailable("Finalized operation still holds a reservation")
        if native_status in {"RESERVED", "DISPATCHED", "UNAVAILABLE"} and reserved != upper:
            _unavailable("Pending operation lost its reservation")
        row = totals.setdefault(owner, {"spent": 0, "reservations": 0})
        row["spent"] = _sum([row["spent"], actual or 0], "window spend")
        row["reservations"] = _sum([row["reservations"], reserved], "window reservations")
    return totals


def _protected_buckets(state: dict, proposal: dict, buckets: list[dict], owners: set[str]) -> dict[str, int]:
    """Verify that origin-tagged unspent pools equal the native global pool."""
    totals: dict[str, int] = {}
    current: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for item in buckets:
        if type(item) is not dict or set(item) != {
            "schemaVersion", "budgetScopeId", "owner", "originWindowId", "unspent"
        } or item["schemaVersion"] != "agent-closing-protection-bucket.v1":
            _unavailable("Protection bucket is malformed")
        if item["budgetScopeId"] != proposal["budgetScopeId"]:
            _unavailable("Protection bucket belongs to another budget scope")
        owner = _owner_key(item["owner"])
        if owner not in owners:
            _unavailable("Protection bucket has an unknown owner")
        origin = item["originWindowId"]
        if type(origin) is not str or not 1 <= len(origin) <= 256 or (owner, origin) in seen:
            _unavailable("Protection bucket origin is missing or duplicated")
        seen.add((owner, origin))
        unspent = _amount(item["unspent"], "unspent protected balance")
        totals[owner] = _sum([totals.get(owner, 0), unspent], "global protection")
        if origin == proposal["closingWindowId"]:
            current[owner] = unspent
    native = state.get("protected")
    if type(native) is not dict or not set(native) <= owners or set(totals) != owners:
        _unavailable("Protection buckets do not cover the native owner inventory")
    for owner, total in totals.items():
        if _amount(native.get(owner, 0), "native protected balance") != total:
            _unavailable("Protection bucket aggregate differs from native accounting")
    return current


def reconstruct_closing_balances(
    state: dict, journal_revision: int, proposal: dict,
    operation_bindings: list[dict], protection_buckets: list[dict], policy_effect_digest: str,
) -> list[dict]:
    """Rebuild all owner rows from persisted membership and current native state.

    A caller must authenticate the proposal, effect, and SQL snapshot separately.
    Returned rows deliberately contain no financial admission or permission.
    """
    if type(state) is not dict or type(proposal) is not dict:
        _unavailable("Native state or closing proposal is missing")
    if proposal.get("schemaVersion") != "agent-closing-resource-proposal.v1":
        _unavailable("Unsupported closing proposal")
    scope = state.get("scope")
    if type(scope) is not dict or (
        proposal.get("budgetScopeId") != scope.get("budget_scope_id")
        or proposal.get("runId") != scope.get("run_id")
    ):
        _unavailable("Closing proposal differs from native budget scope")
    unit = proposal.get("unit")
    if type(unit) is not dict or unit.get("metric") != "reportedTokens" or (
        unit.get("unitDefinitionId") != scope.get("unit_definition_id")
    ):
        _unavailable("Closing unit differs from native accounting")
    if type(operation_bindings) is not list or type(protection_buckets) is not list:
        _unavailable("Closing membership inventory is unavailable")
    if type(policy_effect_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", policy_effect_digest) is None:
        _unavailable("Closing policy effect identity is missing")
    revision = _amount(journal_revision, "journal revision")
    if revision > (1 << 53) - 1:
        _unavailable("Journal revision exceeds the safe-integer domain")
    limits = proposal.get("limits")
    if type(limits) is not list or not limits:
        _unavailable("Closing owner inventory is missing")
    selected: dict[str, dict] = {}
    for item in limits:
        try:
            validate_limit_proposal(item)
        except LifecycleError:
            _unavailable("Closing limit proposal is invalid")
        owner = _owner_key(item["scope"])
        if owner in selected:
            _unavailable("Closing owner is duplicated")
        selected[owner] = item
    tasks = state.get("task_spent")
    if type(tasks) is not dict or set(selected) != {"", *tasks} or selected[""]["participation"] != "CLOSING_ENABLED":
        _unavailable("Closing limits omit or invent a native owner")
    if state.get("qualified") is True and (
        state.get("overhead") is None or any(value is None for value in tasks.values())
        or state.get("opening", {}).get("pending_operations") != []
    ):
        _unavailable("Native qualification contradicts unknown financial facts")
    operation_totals = _window_operations(state, proposal, operation_bindings, policy_effect_digest)
    if not set(operation_totals) <= set(selected):
        _unavailable("Closing operation has no owner")
    for owner in operation_totals:
        if selected[owner]["participation"] != "CLOSING_ENABLED":
            _unavailable("Retained task received a closing operation")
    window_protected = _protected_buckets(state, proposal, protection_buckets, set(selected))
    native = _projection(state, revision)
    qualified = native.qualification == "QUALIFIED" and native.gate_status == "READY"
    status = (
        "QUALIFIED" if qualified else
        native.gate_status if native.gate_status in {"CONFLICT", "BOUND_BROKEN"} else "UNAVAILABLE"
    )
    run_spent = _sum([x["spent"] for x in operation_totals.values()], "run window spend")
    run_reserved = _sum([x["reservations"] for x in operation_totals.values()], "run window reservations")
    rows = []
    for owner, limit in selected.items():
        entry = native.tasks[owner] if owner else None
        known = entry["known_spent"] if entry else native.known_spent
        spent = entry["spent"] if entry else native.spent
        reserved = entry["active_reservations"] if entry else native.active_reservations
        protected = entry["protected_closeout"] if entry else native.protected_closeout
        window = operation_totals.get(owner, {"spent": 0, "reservations": 0})
        if owner == "":
            window = {"spent": run_spent, "reservations": run_reserved}
            pool = _sum(list(window_protected.values()), "run window protection")
        else:
            pool = window_protected.get(owner, 0)
        enabled = limit["participation"] == "CLOSING_ENABLED"
        if not enabled and (window["spent"] or window["reservations"] or pool):
            _unavailable("Retained task acquired new-window resources")
        if protected is not None and pool > protected:
            _unavailable("Window protection exceeds native owner pool")
        rows.append({
            "schemaVersion": "agent-closing-resource-balance.v1",
            "runId": proposal["runId"], "budgetScopeId": proposal["budgetScopeId"],
            "closingWindowId": proposal["closingWindowId"], "journalRevision": revision,
            "unit": unit, "scope": limit["scope"],
            "spentAtActivation": limit["knownSpentAtAnchor"],
            "currentKnownCumulativeSpent": known,
            "currentCumulativeSpent": spent if qualified else None,
            "windowKnownSpent": window["spent"], "windowSpent": window["spent"] if qualified else None,
            "allActiveReservations": reserved,
            "windowActiveReservations": window["reservations"] if reserved is not None else None,
            "globalProtected": protected, "windowProtected": pool if protected is not None else None,
            "cumulativeCeiling": limit["prospectiveCumulativeCeiling"],
            "windowAllowance": limit["approvedAdditional"],
            "priorViolationsDigest": limit["priorViolationSetDigest"], "qualification": status,
        })
    return rows


def _loaded_payload(raw: str, label: str, *, max_bytes: int = 1_048_576) -> dict:
    if type(raw) is not str or len(raw.encode("utf-8")) > max_bytes:
        _unavailable(f"{label} exceeds its input bound")
    try:
        value = json.loads(raw)
        if type(value) is not dict or canonical(value) != raw:
            raise ValueError("Noncanonical payload")
        return value
    except (TypeError, ValueError, RecursionError):
        _unavailable(f"{label} is malformed")


def read_persisted_closing_balances(
    db: sqlite3.Connection, binding: dict, closing_window_id: str,
) -> dict:
    """Reconcile one current window inside the caller's pinned read transaction.

    This checks durable record joins and cache freshness. It does not qualify
    signing authority, native dispatch, or the completeness of a host route.
    """
    if type(closing_window_id) is not str or not 1 <= len(closing_window_id) <= 256:
        _unavailable("Closing window identity is malformed")
    run_id, scope = binding["runId"], binding["budgetScopeId"]
    effect_row = db.execute(
        "SELECT effect_digest,payload FROM closing_policy_effects WHERE run_id=? AND closing_window_id=?",
        (run_id, closing_window_id),
    ).fetchone()
    if effect_row is None:
        _unavailable("Durable closing policy effect is absent")
    record = _loaded_payload(effect_row["payload"], "closing policy record")
    if set(record) != {"effect", "candidate", "proposal", "nativeBeforePolicy", "nativeAfterPolicy"}:
        _unavailable("Closing policy record is incomplete")
    effect, candidate, proposal = record["effect"], record["candidate"], record["proposal"]
    if not all(type(item) is dict for item in (effect, candidate, proposal)):
        _unavailable("Closing policy record has malformed components")
    if (
        effect.get("schemaVersion") != "agent-closing-resource-effect.v1"
        or candidate.get("schemaVersion") != "agent-closing-resource-candidate.v1"
        or proposal.get("schemaVersion") != "agent-closing-resource-proposal.v1"
        or effect_row["effect_digest"] != digest(effect)
        or effect.get("candidateDigest") != digest(candidate)
        or effect.get("proposalDigest") != digest(proposal)
        or candidate.get("proposalDigest") != effect["proposalDigest"]
    ):
        _unavailable("Closing policy record digest chain is broken")
    for item in (effect, candidate, proposal):
        if item.get("runId") != run_id or item.get("budgetScopeId") != scope or (
            item.get("closingWindowId") != closing_window_id
        ):
            _unavailable("Closing policy record differs from the pinned scope")
    if (
        proposal.get("bindingId") != binding["bindingId"]
        or candidate.get("bindingId") != binding["bindingId"]
        or proposal.get("journalIdentity") != binding["journalIdentity"]
        or candidate.get("journalIdentity") != binding["journalIdentity"]
        or candidate.get("inventoryDigest") != proposal.get("inventoryDigest")
        or candidate.get("beforePolicy") != effect.get("beforePolicy")
        or candidate.get("afterPolicy") != effect.get("afterPolicy")
        or type(effect.get("beforeJournalRevision")) is not int
        or not 0 <= effect["beforeJournalRevision"] < (1 << 53) - 1
        or effect.get("beforeJournalRevision") != proposal.get("expectedJournalRevision")
        or candidate.get("expectedJournalRevision") != proposal.get("expectedJournalRevision")
        or type(effect.get("afterJournalRevision")) is not int
        or effect["afterJournalRevision"] != effect["beforeJournalRevision"] + 1
    ):
        _unavailable("Closing policy revision or inventory join is broken")
    event_row = db.execute(
        "SELECT kind,payload,digest FROM events WHERE scope=? AND revision=? AND ordinal=0",
        (scope, effect["afterJournalRevision"]),
    ).fetchone()
    if event_row is None or event_row["kind"] != "CLOSING_POLICY_APPLIED":
        _unavailable("Native closing policy event is absent")
    event = _loaded_payload(event_row["payload"], "native closing policy event")
    if event != record or event_row["digest"] != digest(event):
        _unavailable("Closing policy event differs from durable effect")
    before_native, after_native = record["nativeBeforePolicy"], record["nativeAfterPolicy"]
    if not all(type(item) is dict for item in (before_native, after_native)) or not all(
        type(item) is dict for item in (effect.get("beforePolicy"), effect.get("afterPolicy"))
    ) or (
        before_native.get("policy_id") != effect["beforePolicy"].get("policyId")
        or before_native.get("revision") != effect["beforePolicy"].get("revision")
        or digest(before_native) != effect["beforePolicy"].get("policyDigest")
        or after_native.get("policy_id") != effect["afterPolicy"].get("policyId")
        or after_native.get("revision") != effect["afterPolicy"].get("revision")
        or digest(after_native) != effect["afterPolicy"].get("policyDigest")
    ):
        _unavailable("Closing policy event native policy lineage is broken")
    state_row = db.execute("SELECT revision,data FROM scope_state WHERE scope=?", (scope,)).fetchone()
    if state_row is None or type(state_row["revision"]) is not int or (
        state_row["revision"] < effect["afterJournalRevision"]
    ):
        _unavailable("Current native financial state is absent")
    state = _loaded_payload(state_row["data"], "native financial state", max_bytes=8_388_608)
    policy = state.get("policy")
    after_policy = effect["afterPolicy"]
    if type(policy) is not dict or policy != after_native or (
        policy.get("policy_id") != after_policy.get("policyId")
        or policy.get("revision") != after_policy.get("revision")
        or digest(policy) != after_policy.get("policyDigest")
    ):
        _unavailable("Current native policy differs from closing effect")
    sidecars = []
    for row in db.execute(
        "SELECT operation_id,binding_digest,payload FROM closing_operation_bindings "
        "WHERE budget_scope_id=?", (scope,),
    ):
        sidecar = _loaded_payload(row["payload"], "closing operation binding")
        if (
            sidecar.get("operationId") != row["operation_id"]
            or sidecar.get("budgetScopeId") != scope
            or row["binding_digest"] != digest(sidecar)
        ):
            _unavailable("Closing operation SQL key or digest is broken")
        if sidecar.get("closingWindowId") == closing_window_id:
            sidecars.append(sidecar)
    buckets = []
    for row in db.execute(
        "SELECT owner,origin_window_id,generation,payload FROM closing_protection_buckets "
        "WHERE budget_scope_id=?", (scope,),
    ):
        bucket = _loaded_payload(row["payload"], "closing protection bucket")
        if (
            _owner_key(bucket.get("owner")) != row["owner"]
            or bucket.get("originWindowId") != row["origin_window_id"]
            or type(row["generation"]) is not int
            or not 0 <= row["generation"] <= state_row["revision"]
        ):
            _unavailable("Protection bucket SQL key or generation is broken")
        buckets.append(bucket)
    rebuilt = reconstruct_closing_balances(
        state, state_row["revision"], proposal, sidecars, buckets, effect_row["effect_digest"]
    )
    saved = {}
    stale = False
    for row in db.execute(
        "SELECT owner,generation,payload FROM closing_resource_balances "
        "WHERE budget_scope_id=? AND closing_window_id=?", (scope, closing_window_id),
    ):
        payload = _loaded_payload(row["payload"], "closing resource balance")
        owner = _owner_key(payload.get("scope"))
        if owner != row["owner"] or owner in saved or type(row["generation"]) is not int or (
            row["generation"] > state_row["revision"]
        ):
            _unavailable("Closing resource projection SQL identity is broken")
        saved[owner] = payload
        stale |= row["generation"] != state_row["revision"]
    expected = {_owner_key(row["scope"]): row for row in rebuilt}
    if not stale and set(saved) == set(expected) and saved != expected:
        _unavailable("Fresh closing resource projection differs from native facts")
    return {
        "status": "CURRENT" if not stale and saved == expected else "REBUILD_REQUIRED",
        "balances": rebuilt, "proposal": proposal, "financialAdmission": False,
        "requiresAuthenticatedActivationAndCurrentClaim": True,
    }


def _read_current_closing_resource_data(
    db: sqlite3.Connection, binding: dict, current: dict, closing_window_id: str,
) -> dict:
    """Join current workflow/window and financial rows on one caller-owned connection."""
    state = current.get("state") if type(current) is dict else None
    window = state.get("closingWindow") if type(state) is dict else None
    if type(window) is not dict or window.get("closingWindowId") != closing_window_id:
        raise JournalUnavailable("Requested closing window is not active", write_outcome="NOT_STARTED")
    result = read_persisted_closing_balances(db, binding, closing_window_id)
    effect = db.execute(
        "SELECT effect_digest FROM closing_policy_effects WHERE run_id=? AND closing_window_id=?",
        (binding["runId"], closing_window_id),
    ).fetchone()
    if effect is None or effect["effect_digest"] != window.get("resourcePolicyEffectDigest"):
        raise JournalUnavailable("Workflow closing context differs from policy effect", write_outcome="NOT_STARTED")
    return result


def _read_existing_closing_operation_data(store, sidecar: dict) -> dict:
    """Join current rows for existing membership in an admitted transaction.

    This is diagnostic replay, never a reserve, claim or host permission.
    """
    journal = store._journal
    _require_financial_transaction(journal)
    db = journal._db
    binding = store._binding
    current = store._read_run(db)
    pinned = _resolve_pinned_native_operation_data(journal, binding, store._binding_digest, sidecar)
    window_id = sidecar["closingWindowId"]
    financial = _read_current_closing_resource_data(db, binding, current, window_id)
    if financial["status"] != "CURRENT":
        raise JournalUnavailable("Closing financial projection needs rebuild", write_outcome="NOT_STARTED")
    window = current["state"]["closingWindow"]
    if sidecar["policyEffectDigest"] != window["resourcePolicyEffectDigest"]:
        raise JournalUnavailable("Operation window policy effect differs", write_outcome="NOT_STARTED")
    scope, operation = binding["budgetScopeId"], pinned["operation"]
    saved = db.execute(
        "SELECT binding_digest,payload FROM closing_operation_bindings "
        "WHERE budget_scope_id=? AND operation_id=?", (scope, operation.operation_id),
    ).fetchone()
    if saved is None or saved["binding_digest"] != digest(sidecar) or saved["payload"] != canonical(sidecar):
        raise JournalUnavailable("Immutable closing operation membership differs", write_outcome="NOT_STARTED")
    replay, revision, _, _ = journal._live_facts(scope)
    projected, projected_revision = journal._load(scope)
    stored = replay.get("operations", {}).get(operation.operation_id)
    if (
        projected is None or projected_revision != revision or projected != replay
        or stored is None or stored.get("digest") != operation.binding_digest
        or stored.get("binding") != asdict(operation)
    ):
        raise JournalUnavailable("Existing native operation replay differs", write_outcome="NOT_STARTED")
    return {
        "status": "CURRENT_DATA", "anchor": pinned["anchor"], "operation": operation,
        "workflowRevision": current["revision"], "journalRevision": revision,
        "balances": financial["balances"], "proposal": financial["proposal"],
        "storedOperation": stored, "rootQualificationVerified": False,
        "accountingReplayVerified": True, "financialAdmission": False,
    }


def _read_acknowledged_closing_operation_data(store, sidecar: dict) -> dict:
    """Require current SQL projection ACK before diagnostic operation replay.

    The ACK row is only stored data. This does not verify the external event log,
    operator custody or dispatch authority and cannot grant a financial write.
    """
    journal = store._journal
    _require_financial_transaction(journal)
    validate_closing_operation_binding(sidecar)
    current = store._read_run(journal._db)
    if current["publicationStatus"] != "ACK":
        raise JournalUnavailable("Current workflow projection is not acknowledged", write_outcome="NOT_STARTED")
    if sidecar["expectedWorkflowRevision"] != current["revision"]:
        raise JournalUnavailable("Closing operation workflow revision is stale", write_outcome="NOT_STARTED")
    selected = _read_existing_closing_operation_data(store, sidecar)
    return {
        **selected, "sqlProjectionAckObserved": True,
        "workflowRevisionMatched": True, "nativePermissionGranted": False,
    }


def _read_acknowledged_closing_grant_data(
    store, sidecar: dict, authority_input: dict, grant_raw: bytes,
    clock_observation: dict,
) -> dict:
    """Match current closing context to signed grant at a supplied time; data only."""
    selected = store._read_acknowledged_closing_authority_data_in_transaction(
        sidecar, authority_input,
    )
    grant_data = store._signed_grant_data_in_transaction(
        authority_input, grant_raw, clock_observation,
    )
    try:
        grant = load_json_object(grant_raw, label="signed closing grant")
        state, _ = store._read_authoritative_state(store._journal._db)
        context = state["closingWindow"]
        observed_at = clock_observation["observedAt"]
        if (
            grant_data["currentEpoch"] != selected["authorityEpoch"]
            or grant["permission"] != "closing.activate"
            or grant["closingWindowId"] != sidecar["closingWindowId"]
            or context["closingWindowId"] != sidecar["closingWindowId"]
            or context["windowGrantDigest"] != grant_data["grantDigest"]
            or not (
                _closing_instant(context["validFrom"], "validFrom")
                <= _closing_instant(observed_at, "observedAt")
                < _closing_instant(context["expiresAt"], "expiresAt")
            )
        ):
            raise ValueError("Current closing window differs from signed grant or supplied time")
    except (KeyError, TypeError, ValueError, LifecycleError) as exc:
        raise JournalUnavailable("Closing grant/context data join differs", write_outcome="NOT_STARTED") from exc
    return {
        **selected, "grantData": grant_data,
        "grantDigest": grant_data["grantDigest"],
        "claimHeadroomData": classify_current_claim_data(selected, sidecar),
        "currentWindowDataMatched": True,
        "suppliedTimeInsideWindow": True,
        "rootQualificationVerified": False, "clockQualified": False,
        "grantQualified": False, "financialAdmission": False,
        "nativePermissionGranted": False,
    }


def closed_financial_totals(state: dict, revision: int) -> dict:
    projection = _projection(state, revision)
    if (
        state.get("mode") != "COVERAGE_V2"
        or not state.get("opening_complete")
        or state.get("unresolved_reasons")
        or state.get("input_unavailable")
        or projection.spent is None
        or projection.active_reservations != 0
        or projection.protected_closeout is None
        or state["gate"] not in {"READY", "BOUND_BROKEN", "CLOSED"}
    ):
        raise JournalUnavailable("Full known typed accounting required for closure")
    for baseline in state.get("baselines", {}).values():
        if not isinstance(baseline.get("frontier"), dict):
            raise JournalUnavailable("Untyped or unresolved source frontier cannot close")
    tasks = {key: 0 for key in state["task_spent"]}
    roles = {role: 0 for role in ROLES}
    overhead = 0
    for owner, op in state["operations"].items():
        binding = _operation(op["binding"])
        if (
            op["digest"] != binding.binding_digest
            or binding.operation_id != owner
            or binding.budget_scope_id != state["scope"]["budget_scope_id"]
            or binding.run_id != state["scope"]["run_id"]
            or binding.unit_definition_id != state["scope"]["unit_definition_id"]
            or op["reservation"] != 0
        ):
            raise JournalUnavailable("Closed financial operation binding mismatch")
        if op["state"] == "CANCELLED_WITH_NO_DISPATCH_PROOF":
            amount = 0
        elif op["state"] == "SETTLED" and op["claim_id"] and op["actual"] is not None:
            amount = uint(op["actual"])
            final = state.get("accepted_finals", {}).get(owner)
            if (
                final is None
                or final["receipt"]["reported_tokens"] != amount
                or final["receipt"]["binding_digest"] != op["digest"]
            ):
                raise JournalUnavailable("Settled operation lacks its first final financial binding")
        else:
            raise JournalUnavailable("Unfinished operation cannot close")
        roles[binding.role] += amount
        if binding.task_id is None:
            overhead += amount
        elif binding.task_id in tasks:
            tasks[binding.task_id] += amount
        else:
            raise JournalUnavailable("Financial task attribution missing")
    if (
        tasks != state["task_spent"]
        or overhead != state["overhead"]
        or sum(roles.values()) != projection.known_spent
    ):
        raise JournalUnavailable("Operation facts do not explain complete run/task/role totals")
    return {
        "known_spent": projection.known_spent,
        "tasks": tasks,
        "overhead": overhead,
        "roles": roles,
        "protected": copy.deepcopy(state["protected"]),
        "original_gate": state.get("original_gate", state["gate"]),
        "run_cap": state["policy"]["run_cap"],
        "task_caps": state["policy"]["task_caps"],
        "bound_violations": sorted(
            owner
            for owner, op in state["operations"].items()
            if op["actual"] is not None and op["actual"] > op["binding"]["upper_bound_tokens"]
        ),
    }


__all__ = ["closed_financial_totals", "read_persisted_closing_balances", "reconstruct_closing_balances"]
