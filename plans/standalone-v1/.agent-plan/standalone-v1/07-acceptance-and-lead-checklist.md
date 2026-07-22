# Acceptance And Lead Checklist

## Acceptance Criteria

- AC-NEUTRALITY: bootstrap full-scope scan and the complete neutrality v3
  negative suite emit fresh trusted redacted evidence. Every exact output path
  is operation-unique and absent at scan and create-no-replace publication;
  primary artifacts publish before the detached signed commit receipt, and a
  committed replay is read-only and byte-identical. Producer/verifier digests
  match, frozen numeric archive bounds hold, all `NEUTRALITY_*` inputs pass the
  external no-follow stable-read authority contract, and every required result
  counter is zero.
- AC-NEUTRALITY-RUNTIME: every downstream launch and attempt acceptance binds
  a fresh controller-owned receipt and mandatory redacted Ed25519 attestation
  to the exact current subject, scope, authority, operation-output set and
  signer fingerprint without excluding any prior output; after the accepted
  terminal review, finalization neutrality additionally covers that review and
  every existing artifact before proof, WAL or state output is committed.
- AC-NEUTRALITY-RELEASE: all Git/history/worktree scopes and the immutable
  committed generation referenced by the assembly receipt pass one fresh
  independently recomputed signed scan before read-only release verification;
  verification consumes the same assembly receipt and cannot rebuild.
- AC-FOUNDATION: Python 3.11 through 3.13 metadata, dependency lock and clean
  local installation are reproducible with one canonical source.
- AC-CONTRACTS: schemas, paths, content identities, stable errors, host protocol
  and extension interfaces pass compatibility and boundary tests.
- AC-SDD: S0/S1/S2 clarification, independent reviews, freeze, lineage, reopen
  and refreeze pass positive and stale/forged/self-review negative cases.
- AC-COMPILER: frozen DAG compilation is deterministic, task-local, bounded and
  rejects stale locks, cycles, ownership overlaps and invalid context.
- AC-WORKFLOW: dependency, approval, attempt, review/remediation, cancellation,
  deadline, WAL/CAS, crash, resume, reconciliation and the finite terminal
  audit/post-gate/review/`AWAITING_FINAL_PROOF`/finalization-neutrality/
  controller-proof scenarios pass, including identical and conflicting replay.
- AC-USAGE: every semantic stage has raw counters, normalized host attestation,
  prompt/cache identity and cumulative usage reconciliation.
- AC-RESOURCE: the exact versioned S0/S1/S2 product profile enforces the
  zero-or-one logical-call-per-iteration rule, hard call ceilings per task and
  run, hard context ceilings per call and cumulative run, every other hard
  stage/run ceiling, cumulative counters and compact context rules.
- AC-ROUTING: every stage/role resolves deterministically through an external
  provider-neutral profile, preserves mandatory capability and independence,
  fails closed when unavailable and records the exact selection in usage.
- AC-AUDIT: task and final findings-first audits reconcile frozen scope, exact
  writes, change sets, artifacts and receipts, never self-repair, and reject
  every unresolved Medium, High or Blocker.
- AC-TASK-VERDICT: the workflow accepts a task only after its independent audit
  proves exact packet/result/evidence/usage lineage and has no unresolved
  Medium, High or Blocker; Blocker stops the run immediately.
- AC-CLI: all stable command groups return compact versioned JSON and expose
  full state only explicitly.
- AC-SKILLS: exactly five entries are stage-routed, neutral, semantically
  complete and no larger than 8192 bytes.
- AC-CONFORMANCE: inventoried synthetic S0/S1/S2, security, recovery, resource
  and final-verdict scenarios are deterministic.
- AC-ADAPTER-BASELINE: every included adapter installs/discovers offline,
  validates all envelopes, pins compatibility, declares capabilities/maturity
  and rejects unsupported operations; live proof is optional promotion only.
- AC-COST-BENCHMARK: all two hundred deterministic cold/warm replay runs pass
  absolute p95, hard ceiling and no-quality-regression rules; the first release
  publishes the baseline and later releases also pass relative p50/p95 limits.
- AC-LIVE-COST-CALIBRATION: six bounded live host runs preserve S0/S1/S2
  acceptance and audit verdicts, provide verified usage and remain within the
  separate 120000-token and 7200-second calibration ceiling.
- AC-CODEX, AC-CLAUDE, AC-CURSOR, AC-OPENCODE: each isolated adapter passes the
  offline baseline and publishes evidence-accurate `EXPERIMENTAL` maturity.
- AC-PLATFORM-MATRIX: a controller-approved external allowlist digest, all nine
  CI-owned OS/interpreter receipts and their signed aggregate bind one source,
  lock, command/toolchain identities and identical
  `candidatePayloadInventoryDigest`; none may claim the future
  `finalInventoryDigest`.
- AC-RELEASE: `EV-RELEASE-ASSEMBLY` proves two clean builds reproduce the
  aggregate candidate digest and atomically publish by no-replace rename one
  content-addressed generation with a separate `finalInventoryDigest` and
  write-last commit marker. The exact assembly receipt and committed generation
  then pass neutrality and read-only `--no-build` verification with pre/post
  Merkle equality for wheel, source distribution, bundles, SBOM, notices,
  documentation and provenance.
- AC-FINAL: an independent audit maps every predecessor and the WS-15
  pre-launch gate to current evidence and returns `READY_FOR_FINALIZATION`;
  after its post-attempt gate and accepted review, the controller enters
  `AWAITING_FINAL_PROOF`, runs finalization neutrality, and only then may an
  acyclic body/envelope plus idempotent WAL and expected-revision CAS issue
  `COMPLETE` with no unresolved Medium, High or Blocker.

## Lead Checklist

- Preserve `LICENSE` unchanged and keep immutable plan files separate from
  mutable workflow/results/reviews/evidence.
- Verify the restored round-1 specification snapshot, rejected review, frozen
  revision-1 authority and revision-2/r03 review chain by exact hashes.
- Verify exact reciprocal requirement, workstream, acceptance and evidence ids.
- Verify every author/reviewer/final-auditor actor and run identity is distinct.
- Verify exact write sets, dependency waves and no production path in
  `leadOwned`.
- Verify controller neutrality before every launch and after every attempt.
- Verify every neutrality operation uses unique absent write-once outputs,
  publishes its detached commit receipt last, excludes only its frozen exact
  current outputs and has matching producer/verifier component digests.
- Verify all nine neutrality zero counters and every frozen numeric archive
  bound, including nesting, entry, compressed/expanded byte, ratio and path
  limits.
- Verify `NEUTRALITY_*` authority inputs are absolute, fresh, bounded regular
  files outside workspace, artifact, Git and release roots; reject symlink,
  reparse, hardlink, race, malformed, stale, oversize, bad-signature and
  fingerprint negatives. Rule values, trust material, signing keys and matched
  fragments never enter Git, state, prompts, logs, distributions or evidence.
- Verify deterministic gates precede semantic calls and only stage-relevant
  skills/references are loaded.
- Verify offline adapter maturity, frozen normalized contract inventory, closed
  contract compatibility and optional live promotion semantics.
- Verify product budget profile, benchmark cohorts and all nine matrix legs
  bind one candidate payload digest; verify the two assembly builds reproduce
  it and only assembly defines the separate final inventory. Publish nothing
  remotely from this package.
- Verify atomic no-replace release assembly precedes scan and `--no-build`
  verification and that both consume the same assembly receipt. Then verify
  terminal audit, post-attempt gate, accepted review,
  `AWAITING_FINAL_PROOF`, finalization neutrality and acyclic proof/WAL/CAS
  form one finite crash-recoverable state-bound chain.

## Refreeze Triggers

Scope, accepted behavior, architecture, public contract, write ownership, DAG,
evidence contract or final gate changes require `REOPENED`, a new revision,
independent review and generated refreeze. In-bound implementation/test/evidence
defects may use approved bounded remediation.

## Completion Rule

Every required task is independently accepted, terminal audit status is
`READY_FOR_FINALIZATION`, its post-attempt gate and independent review are
accepted, the run enters `AWAITING_FINAL_PROOF`, and finalization neutrality
passes. The controller's write-once proof envelope, idempotent fsynced WAL append
and expected-revision state CAS then issue `COMPLETE` with fresh
content-addressed evidence and no unresolved Medium, High or Blocker finding.
