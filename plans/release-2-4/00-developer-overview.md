# Developer overview

Release 2.4 is the activated target for an optional security analysis profile,
based on the accepted Release 2.3 merge and rooted in the mandatory 2.0
baseline. The bounded activation case is recorded in
`plans/release-2-4/activation-evidence.md`.

The feature composes existing ALK state and evidence. It does not create a second workflow authority, provider runtime, background service or mandatory artifact for ordinary tasks. The manifest's
`extensions.securityAnalysis.implementationAudit` policy is materialized by
plan adoption and enforced at `accept_task`; a helper-level check is not enough.
No implementation begins until a concrete activation case proves the extra
contract is necessary.

## Dependency rule

Contracts remain standard-library-only and authority-free. Optional host behavior stays behind adapter boundaries. Views and imported results remain untrusted until checked by the authoritative workflow.

## Freeze rule

Update `baseRevision.sha` to the accepted Release 2.3 merge, reconcile
separately accepted candidates, keep the plan package Git-visible under
`plans/release-2-4/`, increment `planRevision`, rerun structural checks, close
independent S2 findings and only then generate `plan.lock.json`. A final
activation receipt must execute every safe fixture step and prove zero live or
out-of-evidence side effects.
