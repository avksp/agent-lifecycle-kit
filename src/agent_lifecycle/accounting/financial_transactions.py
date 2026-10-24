"""Reservation and claim mutations within an already admitted journal transaction.

These primitives confer no host, provider or dispatch authority.
"""

from dataclasses import asdict

from .contracts import (
    JournalUnavailable,
    Operation,
    RevisionConflict,
    _BindingConflict,
    _JournalStoragePort,
    _projection,
    digest,
    identity,
    uint,
)


def _require_financial_transaction(journal: _JournalStoragePort) -> None:
    journal._check_owner()
    if not journal._db.in_transaction or journal._admission_depth != 1:
        raise JournalUnavailable("Financial operation requires admitted transaction", write_outcome="NOT_STARTED")


def _reserve_in_transaction(
    journal: _JournalStoragePort, operation: Operation, *, expected_revision: int | None = None
) -> str:
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
    if not _reservation_fits(state, revision, operation):
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


def _claim_in_transaction(
    journal: _JournalStoragePort, scope: str, operation_id: str, binding_digest: str, claim_id: str
) -> str:
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


def _reservation_fits(state: dict, revision: int, operation: Operation) -> bool:
    policy = state["policy"]
    projected = asdict(_projection(state, revision))
    owner = operation.task_id if operation.task_id is not None else ""
    upper = operation.upper_bound_tokens
    transfer = upper if operation.operation_class == "CLOSEOUT" else 0
    if transfer and state["protected"].get(owner, 0) < transfer:
        return False
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
            return False
    return True
