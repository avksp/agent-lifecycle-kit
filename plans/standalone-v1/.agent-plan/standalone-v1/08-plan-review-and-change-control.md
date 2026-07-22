# Plan Review And Change Control

## Revision History

- Plan revision 1: standalone S2 specification and decision-complete execution
  plan.
- Specification review round 1: `CHANGES_REQUIRED` for signature trust,
  capability routing and adapter baseline semantics.
- Specification authoring round 2: defined external Ed25519 trust, deterministic
  stage/role routing and explicit EXPERIMENTAL versus VERIFIED adapter gates.
- Plan review round 1: `CHANGES_REQUIRED` with two High and four Medium findings
  covering executable neutrality, severity thresholds, review lineage, offline
  adapters, product budgets and platform evidence.
- Specification revision 2 and plan revision 2: preserve the exact first
  specification-review subject, strengthen task/final completion, split
  neutrality gates, freeze product budgets and authority inventories, make
  adapter work offline and require nine matrix receipts.
- Specification review r03: `CHANGES_REQUIRED` because the machine budget
  authority did not explicitly freeze logical semantic-call ceilings per task
  and run or a hard cumulative-context-per-run ceiling.
- Specification revision 3: adds those exact ceilings, defines one semantic
  iteration as zero or one logical call, and makes task/run counters cumulative
  across attempts, review, remediation, fallback and cache reuse.
- Specification review r04: `READY_TO_PLAN`; all six dimensions pass and
  `SPEC-001` through `SPEC-004` are resolved. Specification revision 3 is
  frozen by the append-only r03 receipt before plan review.
- Plan review r02: `CHANGES_REQUIRED`; `PLAN-001` through `PLAN-006` are
  resolved, while `PLAN-007` rejects duplicated `workers[*].dependsOn` because
  `workstreams[*].dependsOn` is the sole canonical DAG. The corrected candidate
  removes every worker dependency field without changing workstream edges.
- Plan revision 3: increments the reviewed subject as required by change
  control, retains r02 by exact content identity and carries only the PLAN-007
  correction into the final r03 review round.
- Execution attempt `WS-01` round 1: independent task review reports
  `PLAN-WS01-ENTRYPOINT` as a High plan gap because `VAL-NEUTRALITY` used the
  package-level `python -m agent_lifecycle` entry point before WS-07 owns
  `src/agent_lifecycle/__main__.py`; no implementation changes or evidence were
  accepted for that attempt.
- Plan revision 4: reopens revision 3, preserves WS-07 ownership of the public
  package entry point, changes only the WS-01 bootstrap command to
  `python -m agent_lifecycle.neutrality`, retains the exact r03 review identity
  in `planFiles`, and receives full review r04 `CHANGES_REQUIRED` for
  `PLAN-NEUTRALITY-SUBJECT-FIXPOINT`, `PLAN-RELEASE-PAYLOAD-ORDER` and
  `PLAN-FINAL-POST-GATE-CYCLE`.
- Specification revision 4: defines exact current-operation output projection,
  immutable release assembly before scan and a finite terminal
  audit/post-gate/review/controller-proof chain.
- Specification review r05: `CHANGES_REQUIRED`. The append-only report keeps
  `SPEC-001` through `SPEC-004` resolved and opens `SPEC-005` through
  `SPEC-008`: neutrality lacked a complete write-once detached commit,
  external authority names/rules drifted, release candidate/final identity was
  ambiguous, and final proof still had a self-reference and post-review cycle.
  No specification freeze receipt was issued for revision 4.
- Plan revision 5: unfrozen intermediate candidate based on rejected
  specification r04. It is superseded without claiming an independent r05 plan
  review or freeze.
- Specification revision 5: `REOPENED` candidate. Neutrality profile v3 freezes
  operation-bound absent paths, content-bound primary artifacts, a detached
  receipt written last, exact no-follow stable reads, numeric archive bounds
  and one external `NEUTRALITY_*` authority contract. Release profile v1
  separates `candidatePayloadInventoryDigest` from `finalInventoryDigest` and
  atomically publishes one content-addressed generation. Final-proof profile
  v2 adds `AWAITING_FINAL_PROOF`, finalization neutrality, a fixed operation
  path, acyclic body/envelope digests and idempotent CAS/WAL recovery.
- Plan revision 6: synchronizes task contracts, commands, evidence and
  developer guidance with specification r05; `ci-matrix-profile.v2.json`
  carries the non-recursive candidate payload identity across every matrix
  leg. The candidate preserves the 15-task DAG, exact write ownership and
  prior review lineage. It remains `REOPENED` and unexecutable.
- The rejected plan-review-r01 subject was not preserved before its mutable
  draft files changed. `reviews/plan-review-r01-subject-disclosure.json`
  records that gap fail-closed. The revision-2 review still references the
  exact r01 review artifact as `previousReview`, retains a disposition for
  every r01 finding and performs a full review rather than claiming replay of
  the unavailable subject.

## Review Budget And Stable Findings

- Maximum three plan-review rounds per initial-plan or refreeze cycle.
- Preserve finding ids and predecessor hashes. If an unfrozen reviewed subject
  is unavailable, disclose it, retain the prior review link and require a full
  new review. Never fabricate a missing subject snapshot.
- Intermediate revisions may use delta review; the final freeze candidate must
  receive a full review across all ten required dimensions.
- Budget exhaustion yields `BLOCKED`/`NEEDS_HUMAN`, never readiness.

## Independent Full Review

The specification author, specification reviewer, plan author, plan reviewer,
task workers, task reviewers and final auditor use distinct run identities.
Store machine reports under `reviews/`; only a full `READY_TO_PLAN` can freeze
the specification and only a full `READY_TO_FREEZE` can freeze the plan.

The next valid sequence is an independent review of specification r05 linked
to rejected review r05, a specification-r05 freeze receipt, then a full
independent review of plan r06 and plan refreeze. A reviewer must inspect the
entire candidate, not merely the four corrected findings. Until both freezes
complete, no packet compilation, authorization reuse or task launch is valid.

## Freeze And Refreeze Procedure

Use deterministic validators and freeze commands from the reviewed lifecycle
tooling. Any change to scope, requirement wording, architecture, task ownership,
DAG, proof or release gates increments the relevant revision and repeats the
independent review. Never edit a frozen lock or packet set in place.

## Execution Start And Remediation Modes

- Start mode: `approval-required`.
- Remediation mode: `ask`.
- Implementation defects, test gaps and missing in-scope evidence may be
  remediated within the same frozen packet after approval.
- Architecture, contract, scope, ownership and plan gaps require `REOPENED` and
  refreeze.

## Durable Workflow State

Mutable run state lives under `workflow/`, separate from the frozen plan. The
controller must resume from that state, never from chat history.
