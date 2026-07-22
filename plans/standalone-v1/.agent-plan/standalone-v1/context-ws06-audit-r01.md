# WS-06 Audit Context Projection

This compact projection supplements the frozen task packet. Requirement,
acceptance, evidence, ownership and write-set fields in that packet are
authoritative.

## Step audit

- Validate the task result and evidence receipts against the exact frozen
  command, operation binding, source revision, plan digest and task attempt.
- Compare the implementation change set with exact actor writes and forbidden
  writes; reject undeclared, aliased or cross-owner mutation.
- Report findings first with stable ids, severity, evidence and disposition.
  The auditor never silently repairs implementation.
- `ACCEPTED` requires every required check to pass and no unresolved MEDIUM,
  HIGH or BLOCKER finding. Contract or ownership drift routes to lead review,
  `REOPENED` and refreeze.

## Terminal audit

The independent terminal audit reconciles every predecessor task result,
accepted review, evidence receipt, resource ledger, controller gate, release
generation, platform aggregate, frozen lock and final implementation change
set through the terminal pre-launch gate. A clean pre-proof audit reports
`READY_FOR_FINALIZATION`; it must not claim its future post-attempt gate,
review, finalization neutrality, proof, WAL append, state CAS or `COMPLETE`.

Legacy completed-run artifacts may remain readable, but new schema-3 runs use
the pre-proof verdict and controller finalization protocol. Negative tests must
reject stale, substituted, oversized, operation-mismatched and self-asserted
evidence.
