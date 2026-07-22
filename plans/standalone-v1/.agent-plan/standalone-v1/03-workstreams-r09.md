# Workstreams

## WS-01 Bootstrap Package And Neutrality Boundary

Create the dependency lock, minimal package shell, neutral policy/schema,
security contract, fail-closed scanner, redacted attestation format, local
controller-validation runner and complete negative suite. Execute the generic
repository-policy bootstrap scan and stdlib package/negative test gates without
`pytest` or host-operation approval. Implement the downstream neutrality gate
entrypoint for the v3 external `NEUTRALITY_*` authority contract: exact
operation-bound output descriptors, absent write-once paths, content-bound
primary artifacts, detached receipt published last, portable no-follow stable
reads, numeric archive limits, bounded fresh external authority and
producer/verifier parity. Occupied, partial, replay-mismatched, aliased, raced
or archive-limit subjects fail closed. This is the only first-wave
implementation task; WS-02 cannot launch until its local bootstrap evidence and
controller receipts verify.

## WS-02 Public Contracts, Schemas And Host Protocol

Create canonical lifecycle schemas, stable error codes, repository-relative
path types, content identities, change-set interfaces and the versioned
provider-neutral host-operation protocol. Depends on WS-01.

## WS-03 Specification, Planning, Review And Freeze

Implement SDD S0/S1/S2 clarification, product specification, independent
review, plan analysis, immutable freeze, lineage, reopen and refreeze services.
Depends on WS-02.

## WS-04 Frozen DAG Task Compiler

Compile only hash-verified frozen plans into deterministic, task-local packet
projections with exact ownership, gates, evidence and context ceilings.
Depends on WS-02.

## WS-05 Durable Workflow, Usage And Resource Control

Implement CAS/WAL state, events, approval, dependency waves, task attempts,
review/remediation, cancellation, deadlines, recovery, compact output, prompt
envelopes, deterministic external capability routing, the end-to-end
host-attested usage ledger and controller pre-launch/post-attempt neutrality
gates. Enforce task `ACCEPTED` only after an independent audit reports no open
Medium, High or Blocker finding. After accepted terminal review, enter
`AWAITING_FINAL_PROOF`, run finalization-neutrality and implement the acyclic
fixed-operation-path proof plus idempotent fsynced WAL and expected-revision
CAS transaction that alone reaches `COMPLETE`. Depends on WS-02.

## WS-06 Independent Audit And Change Sets

Implement pluggable change-set providers plus findings-first task/final audit
against frozen contracts, exact writes and content-addressed evidence. Audit
verdicts preserve every finding and never repair implementation silently.
Depends on WS-02.

## WS-07 Stable CLI Composition

Compose the public compact JSON CLI without duplicating domain rules. Depends
on WS-03, WS-04, WS-05 and WS-06.

## WS-08 Five Canonical Thin Skills

Author exactly five stage-routed, project-neutral and surface-neutral skills.
Each entry stays below 8192 bytes and delegates deterministic behavior to the
stable CLI. Depends on WS-07.

## WS-09 Synthetic Conformance And Cost Benchmarks

Create an inventoried synthetic fixture generator, S0/S1/S2 lifecycle and
negative security/recovery scenarios, including write-once output occupancy,
partial publication, external-authority races, archive bombs, release
transaction crashes and finalization replay, plus OS determinism tests and the frozen
deterministic synthetic-host replay corpus with two hundred cold/warm runs and
zero live model invocations. Prove the shared offline adapter baseline and
maturity rules before surface-specific work. Depends on WS-07.

## WS-10 Codex Adapter

Build and test the adapter entirely offline from the frozen contract inventory,
pin its closed contract compatibility
descriptor and emit honest `EXPERIMENTAL` evidence. Live promotion is optional
and outside the required DAG. Depends on WS-08 and WS-09.

## WS-11 Claude Adapter

Build and test the adapter entirely offline from the frozen contract inventory,
pin its closed contract compatibility
descriptor and emit honest `EXPERIMENTAL` evidence. Live promotion is optional
and outside the required DAG. Depends on WS-08 and WS-09.

## WS-12 Cursor Adapter

Build and test the adapter entirely offline from the frozen contract inventory,
pin its closed contract compatibility
descriptor and emit honest `EXPERIMENTAL` evidence. Live promotion is optional
and outside the required DAG. Depends on WS-08 and WS-09.

## WS-13 OpenCode Adapter

Build and test the adapter entirely offline from the frozen contract inventory,
pin its closed contract compatibility
descriptor and emit honest `EXPERIMENTAL` evidence. Live promotion is optional
and outside the required DAG. Depends on WS-08 and WS-09.

## WS-14 Governance And Release Engineering

Complete public documentation, contribution/security governance, notices,
reproducible wheel/source/adapter builds, SBOM, checksums, provenance, nine
authenticated platform-matrix legs, aggregate verification and full
history/release-payload neutrality. Dispatch requires the controller-approved
external CI allowlist digest before the first leg starts. Run the six bounded
live cost-calibration cases through the separately approved provider-neutral
model profile and baseline authority. Every matrix leg and both isolated clean
builds bind one `candidatePayloadInventoryDigest`. Publish the closed release
unit as one write-once content-addressed generation with a separate
`finalInventoryDigest` and last-written commit marker; then scan and verify the
exact committed generation read-only without rebuilding. Depends on WS-08
through WS-13.

## WS-15 Independent Integrated Audit

Audit the exact frozen source revision, full Git object set, release inventory,
requirement traceability, all task reviews, usage/resource ledgers and adapter
maturity through the WS-15 pre-launch gate. Emit `READY_FOR_FINALIZATION` with
no unresolved Medium, High or Blocker finding. This task writes final evidence
only and never claims its future post-attempt gate, task review or finalization.
After its attempt is independently accepted, the controller enters
`AWAITING_FINAL_PROOF`, runs finalization neutrality and commits the fixed-path
proof/WAL/state transaction that alone may issue `COMPLETE`. Depends on WS-14.
