# WS-02 Contract Context Projection

The frozen task packet is authoritative for REQ-CONTRACTS, AC-CONTRACTS,
EV-CONTRACTS, ownership and writes. This projection supplies only the
cross-cutting contract rules needed by the worker.

- Define closed, versioned normalized contracts for specification, plan,
  review, freeze, task packet, workflow state, WAL, authorization, task result,
  task review, evidence receipt, usage ledger, controller gate and final proof.
- Keep immutable plan/specification artifacts separate from mutable workflow
  state and evidence. All identities use canonical bytes and explicit digests.
- Schema 3 validation operations bind run, package, task, attempt, phase,
  validation operation, derived command operation, plan and source revision.
- Host adapters expose capabilities through normalized provider-neutral
  contracts; provider names, model names and secrets never enter core schemas.
- Unknown fields, unknown enum values, stale versions, path traversal,
  ambiguous roots and incomplete identity bindings fail closed.
- Preserve legacy read compatibility only through explicit migrations; new
  writes use the current closed schemas.

Contract tests include positive round trips plus unknown-field, substitution,
version, canonicalization, path and cross-run replay negatives.
