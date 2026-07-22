# Validation And Evidence

## Requirement To Acceptance To Evidence Matrix

| Task | Requirements | Acceptance | Evidence |
| --- | --- | --- | --- |
| WS-01 | REQ-NEUTRALITY, REQ-FOUNDATION | AC-NEUTRALITY, AC-FOUNDATION | EV-NEUTRALITY, EV-NEUTRALITY-NEGATIVE, EV-FOUNDATION |
| WS-02 | REQ-CONTRACTS | AC-CONTRACTS | EV-CONTRACTS |
| WS-03 | REQ-SDD | AC-SDD | EV-SDD |
| WS-04 | REQ-COMPILER | AC-COMPILER | EV-COMPILER |
| WS-05 | REQ-WORKFLOW, REQ-USAGE, REQ-RESOURCE, REQ-ROUTING, REQ-NEUTRALITY-RUNTIME, REQ-TASK-VERDICT | AC-WORKFLOW, AC-USAGE, AC-RESOURCE, AC-ROUTING, AC-NEUTRALITY-RUNTIME, AC-TASK-VERDICT | EV-WORKFLOW, EV-USAGE, EV-RESOURCE, EV-ROUTING, EV-NEUTRALITY-RUNTIME, EV-TASK-VERDICT |
| WS-06 | REQ-AUDIT | AC-AUDIT | EV-AUDIT |
| WS-07 | REQ-CLI | AC-CLI | EV-CLI |
| WS-08 | REQ-SKILLS | AC-SKILLS | EV-SKILLS |
| WS-09 | REQ-CONFORMANCE, REQ-ADAPTER-BASELINE, REQ-COST-BENCHMARK | AC-CONFORMANCE, AC-ADAPTER-BASELINE, AC-COST-BENCHMARK | EV-CONFORMANCE, EV-ADAPTER-BASELINE, EV-COST-BENCHMARK |
| WS-10 | REQ-CODEX | AC-CODEX | EV-CODEX |
| WS-11 | REQ-CLAUDE | AC-CLAUDE | EV-CLAUDE |
| WS-12 | REQ-CURSOR | AC-CURSOR | EV-CURSOR |
| WS-13 | REQ-OPENCODE | AC-OPENCODE | EV-OPENCODE |
| WS-14 | REQ-RELEASE, REQ-NEUTRALITY-RELEASE, REQ-PLATFORM-MATRIX, REQ-LIVE-COST-CALIBRATION | AC-RELEASE, AC-NEUTRALITY-RELEASE, AC-PLATFORM-MATRIX, AC-LIVE-COST-CALIBRATION | EV-RELEASE-ASSEMBLY, EV-RELEASE, EV-NEUTRALITY-RELEASE, nine EV-MATRIX leg ids, EV-MATRIX-AGGREGATE, EV-LIVE-COST-CALIBRATION |
| WS-15 | REQ-FINAL | AC-FINAL | EV-FINAL |

Every requirement statement appears verbatim in exactly one workstream
`plannedItems` entry. Acceptance and evidence ids are reciprocal and complete.

## Bootstrap And Runtime Neutrality Evidence

- WS-01 runs both the complete negative suite and a full bootstrap scan over
  the current repository and Git object set. WS-02 cannot launch until both
  evidence artifacts bind the same source revision, neutrality v3 profile and
  external trust contract.
- The manifest defines a controller-owned pre-launch and post-attempt command
  plus receipt template under `workflow/gates/{gateId}/{taskId}/attempt-{attempt}/`.
  Every downstream launch gate and task review verifies the latest
  subject-bound generic receipt and its mandatory redacted Ed25519 attestation.
- `neutrality-authority-profile.v3.json` is the exact machine authority for
  gate identity, the `NEUTRALITY_*` external input boundary, freshness,
  signatures, write-once subject projection, archive limits and zero counters.
  Every operation freezes an ordered exact-path output descriptor set. Each
  path must be unique and absent at scan and immediately before publication;
  primary artifacts are content-addressed and published create-if-absent
  before the detached signed receipt, which is published last as the commit
  marker. A committed same-operation replay is read-only and byte-identical;
  partial, occupied, reused, aliased, substituted or raced outputs fail closed
  and remain visible to later scans.
- Declared current-operation outputs are signed scope inputs, not skips. All
  other outputs remain scanned. Producer and verifier use the same no-follow,
  handle-relative stable reads and recompute output-manifest, primary-artifact,
  archive-policy, external-authority, worktree, Git-object, inventory, scope,
  subject and claims digests. Producer alone receives the signing key.
- WS-14 reruns full history, unreachable-object and recursively expanded
  committed-generation scope. WS-15 and the later finalization transaction
  independently verify authority, signatures, identities, freshness and every
  required zero counter.
- Rule values, detailed matching fragments, trust roots and private keys stay
  outside packets, Git, state, prompts, logs and evidence payloads.

## Per-Task Commands And Receipts

- Every schema 3 command has a positive timeout, one owner/task id and one
  bounded artifact under that task's evidence root.
- Write-once validation commands use one controller-allocated operation
  binding per run/task/attempt/phase transaction. Frozen command, artifact and
  receipt templates render that binding; every participating command reports
  the same closed operation object, and a new attempt or validation
  transaction receives a new operation id. Static revision-labelled output
  paths are not accepted as retry identity.
- A separate bounded receipt binds validator id/version, source revision,
  environment profile, command identity, operation binding, artifact
  hash/bytes, timestamp and exit status. Acceptance never trusts file
  existence alone.
- Evidence reuse is forbidden for task acceptance. Deterministic release
  comparison may reuse only an identical source revision and toolchain lock.
- Core and all five required adapter tasks run without network. Live adapter
  promotion is optional, separately authorized and never raises required
  release maturity without fresh host-owned evidence.
- Task `ACCEPTED` requires no unresolved Medium, High or Blocker finding.

## Product Cost Evidence

`agent-lifecycle-budget-profile.v1.json` freezes hard product ceilings, stage
token limits, the synthetic corpus, absolute p95 targets, first-release
baseline creation and later relative p50/p95 regression rules.
`EV-RESOURCE` verifies the zero-or-one-call-per-iteration rule, explicit
per-task and per-run logical-call ceilings, per-call and cumulative-run context
ceilings, cumulative counter behavior across attempts/review/remediation/
fallback, and fail-closed enforcement; `EV-COST-BENCHMARK` verifies at
least twenty cold and twenty warm deterministic replay runs per scenario with
zero live model invocations, scenario-specific replayed semantic calls, valid
synthetic host attestations and no quality regression.

`benchmark-authority-profile.v1.json` freezes the long-lived baseline signing
sequence and bounded live calibration authority. `EV-LIVE-COST-CALIBRATION`
verifies six live runs, host-attested usage, unchanged semantic verdicts and
the separate 120000-token/7200-second ceiling. Missing external authority
blocks WS-14 rather than weakening or fabricating the evidence.

## Platform Matrix Evidence

`10-release-matrix.md` and `ci-matrix-profile.v2.json` define nine exact
OS/interpreter legs and the external authority contract. WS-14 cannot dispatch
until the controller verifies and records one signed external allowlist digest.
Each EV-MATRIX id has its own CI-owned receipt and binds the same non-recursive
`candidatePayloadInventoryDigest` over payload bytes only.
`EV-MATRIX-AGGREGATE` rejects missing, stale, duplicate, incompatible or
mismatched legs, a different candidate digest or a changed allowlist. It binds
the exact nine-leg set and candidate digest and is forbidden from claiming the
future `finalInventoryDigest`. A local single-host result cannot satisfy
production release readiness.

## Ordered Release Evidence

WS-14 commands are data-dependent and run in this order after the nine matrix
legs, matrix aggregate and live calibration:

1. Every matrix leg and the authenticated aggregate bind one identical
   `candidatePayloadInventoryDigest` over the candidate payload objects.
2. `VAL-RELEASE-ASSEMBLY` performs two isolated clean builds and requires both
   candidate digests to equal the aggregate. It stages the closed release unit,
   computes a separate `finalInventoryDigest`, writes the commit marker last,
   fsyncs, and atomically renames with no replace to
   `release/generations/{finalInventoryDigest}`. Only the committed generation
   and its operation-scoped assembly receipt are authoritative.
3. `VAL-NEUTRALITY-RELEASE` consumes that exact assembly receipt and scans the
   committed generation under neutrality v3 and its frozen numeric archive
   bounds.
4. `VAL-RELEASE` consumes the same assembly receipt, matrix aggregate and
   neutrality receipt with `--no-build`, traverses the generation read-only and
   proves pre/post Merkle equality.

Missing inputs, changed bytes, mutable aliases, orphan staging, occupancy,
substitution or any candidate/final digest mismatch fail closed.

## Final Gates

`VAL-FINAL` is a terminal-task audit and may emit only
`READY_FOR_FINALIZATION`. It covers WS-01 through WS-14 and the WS-15
pre-launch gate; it does not claim its own future post-attempt gate or review.
After that output, the controller runs the WS-15 post-attempt gate, records the
independent accepted task review and enters `AWAITING_FINAL_PROOF`. Only then
does it run finalization neutrality over that review and every prior artifact.
The content-addressed transaction defined by
`final-proof-authority-profile.v2.json` may transition to `COMPLETE` only after
that projection passes.

The final proof is acyclic: its closed body contains normalized bindings but no
body, envelope or artifact-path self identity; `proofBodyDigest` exists only in
the signed envelope, while `envelopeDigest` exists only in the completion WAL
record and `COMPLETE` state. The proof envelope is create-if-absent, the WAL
append is idempotent and fsynced, and state replacement uses the expected
revision/digest CAS. Recovery after a crash before proof, between proof and WAL,
between WAL and state, or after state must reproduce the same operation; an
identical replay returns the same identities and a conflicting replay blocks.

- Verify the frozen specification lineage, plan lock, compiled packet index
  and exact source revision.
- Reconcile the union of accepted task change sets with the full final change
  set and every exact write-set ceiling.
- Verify every bootstrap, runtime and release neutrality receipt, then run the
  post-review finalization-neutrality projection with the same external
  authority contract.
- Run schema/API compatibility, S0/S1/S2, review/refreeze, ownership, security,
  crash/recovery, cancellation and resource exhaustion conformance.
- Validate every adapter's offline compatibility descriptor, install/discovery,
  capability, unsupported-operation and evidence-accurate maturity behavior.
- Compare deterministic cold/warm p50/p95 usage with absolute product SLOs;
  publish the first signed baseline or, on later releases, verify the prior
  signed baseline and relative limits without removing independent review.
- Verify all nine authenticated platform legs, aggregate, two-build
  reproducibility, dependencies, licenses, SBOM, provenance and clean install.

## Thresholds And Verdict Rules

- Neutrality findings, skipped inputs, opaque inputs, read races, incomplete
  scans, unsupported archives, archive-limit breaches, occupied-output
  conflicts and path-alias conflicts: zero.
- Required schema, lifecycle, security, recovery and resource tests: 100% pass.
- Write overlaps and orphan requirement/acceptance/evidence links: zero.
- Each skill entry size: at most 8192 bytes.
- Required adapter maturity: evidence-accurate `EXPERIMENTAL`; no unsupported
  operation may be presented as supported.
- Matrix legs: exactly nine valid receipts and one valid aggregate bound to one
  `candidatePayloadInventoryDigest`; no matrix artifact claims a
  `finalInventoryDigest`.
- Both clean-build candidate digests equal the matrix aggregate; the separate
  final inventory and committed generation are immutable and content-addressed.
- Task verdict: `ACCEPTED` only with no unresolved Medium, High or Blocker.
- Terminal audit evidence: `READY_FOR_FINALIZATION` only with no unresolved
  Medium, High or Blocker and no missing predecessor evidence.
- Final verdict: `COMPLETE` only from `AWAITING_FINAL_PROOF` after
  finalization neutrality and the controller's acyclic proof/WAL/CAS transaction
  bind the terminal audit, post-attempt gate, accepted review and unchanged
  final change set.
