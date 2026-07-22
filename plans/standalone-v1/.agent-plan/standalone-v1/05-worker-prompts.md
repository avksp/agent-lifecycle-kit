# Worker Prompts

Do not issue worker prompts while specification r05 and plan r06 remain
`REOPENED`. They require matching independent reviews, specification freeze,
plan refreeze and a newly generated `plan.lock.json`.

## Common Contract

Read the canonical task packet and only its frozen references. Modify only the
exact write set. Run deterministic gates before semantic inspection. Return
result v2 with exact changed files, item outcomes, command/evidence receipts,
assumptions, usage and blocker/contract-change fields. Never self-review.

Before launch, verify the controller-provided current-subject neutrality
receipt. After each attempt, invoke the controller-owned gate with an external
host-provided deny set. Never persist or echo external rule values, trust roots
or private keys. Under neutrality v3, use only operation-bound canonical output
descriptors and unique paths absent for the new operation. Publish every
content-bound primary artifact create-if-absent before the detached signed
receipt, which is the last commit marker. Never overwrite, reuse, alias or
exclude a directory, glob, previous/partial output or undeclared path; never
count the exact current outputs as skipped inputs. Enforce no-follow stable
reads, numeric archive bounds and producer/verifier digest parity.
Never copy external samples, evaluations, paths, commands, documents,
artifacts, profiles or repository history.

## Task-Specific Goals

- WS-01: create the neutral package shell and prove the neutrality-v3
  write-once boundary, external authority contract, archive limits, negative
  suite and full bootstrap scan before any extraction, skill, fixture or
  adapter work.
- WS-02: freeze canonical schemas, path/content identities, host operations and
  provider/change-set interfaces.
- WS-03: implement clarification, S0/S1/S2 specification/plan review, freeze,
  lineage, reopen and refreeze semantics.
- WS-04: implement deterministic frozen-DAG task projection and publication.
- WS-05: implement resumable state/WAL, compact projections, budgets, prompt
  envelopes, deterministic capability routing and complete stage usage
  accounting, including pre-launch/post-attempt neutrality hooks,
  `AWAITING_FINAL_PROOF`, finalization neutrality and the acyclic controller
  proof/WAL/state transaction after terminal task acceptance.
- WS-06: implement findings-first task/final audit and pluggable change sets.
- WS-07: expose stable compact JSON CLI commands without domain duplication.
- WS-08: author exactly five thin, stage-routed semantic skills.
- WS-09: create all conformance, fixtures, evaluations and cost baselines from
  synthetic generators, including output occupancy/partial/race/archive,
  release crash/substitution and finalization crash/replay negatives, the
  shared adapter inclusion/promotion baseline and frozen S0/S1/S2 budgets.
- WS-10..WS-13: build one host adapter offline, pin its compatibility source
  and range, keep model profiles external to core, and publish evidence-accurate
  `EXPERIMENTAL` maturity.
- WS-14: collect nine authenticated matrix legs that bind one candidate payload
  digest, aggregate them, reproduce that digest in two clean builds, atomically
  publish one content-addressed final generation with a separate final digest
  and last-written commit marker, then scan and verify it read-only without
  publishing remotely.
- WS-15: audit predecessors and the pre-launch gate only, emit
  `READY_FOR_FINALIZATION`, never claim its future post-attempt gate/review and
  never edit implementation files. Finalization neutrality and the fixed-path
  proof/WAL/state commit remain controller-owned after task acceptance.
