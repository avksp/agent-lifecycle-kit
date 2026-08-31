# Guided workflow continuation

`agent-lifecycle workflow continue` projects the next workflow action and can
explicitly apply either one existing transition or an ordered, bounded bundle
until ALK reaches an external boundary. It is a smaller operator interface,
not a second state machine: workflow state, the frozen plan, the plan lock and
the command-specific transition validators remain authoritative.

## Project first

Projection is the default and is read-only:

```bash
agent-lifecycle workflow continue \
  --state work/run.state.json \
  --manifest work/plans/release-x/plan.manifest.json \
  --lock work/plans/release-x/plan.lock.json \
  --operation-id continue-WS-01 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --reason "project the next bounded action"
```

The receipt returns one of `READY`, `INPUT_REQUIRED`, `WAITING` or `BLOCKED`,
with `stateWritten: false`, `modelCallsStarted: false` and
`hostLaunchStarted: false`. `requiredInputs` names the exact external artifacts
or task selection needed for the current route.

## Apply one projected transition

Reuse the same operation id and supplied inputs. Carry the exact
`action.stateRevision` and `action.actionDigest` from the projection:

```bash
agent-lifecycle workflow continue \
  --state work/run.state.json \
  --manifest work/plans/release-x/plan.manifest.json \
  --lock work/plans/release-x/plan.lock.json \
  --operation-id continue-WS-01 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --reason "apply the reviewed task outcome" \
  --task WS-01 \
  --review work/WS-01/attempt-1/task-review.json \
  --implementation-audit work/audits/WS-01.json \
  --apply \
  --projected-state-revision 7 \
  --projected-action-digest <action-digest>
```

A successful apply returns `APPLIED`, advances state by exactly one revision
and records the normal event of the reused transition. Missing inputs return
`INPUT_REQUIRED`; stale state, action, plan, lock, source or artifact lineage
returns `BLOCKED`. Neither outcome starts a model or host process.

## Apply a bounded bundle

Use bounded mode only when each candidate transition and its explicit
operation ID are already declared in a lineage-bound input bundle:

```bash
agent-lifecycle workflow continue \
  --state work/run.state.json \
  --manifest work/plans/release-x/plan.manifest.json \
  --lock work/plans/release-x/plan.lock.json \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --reason "apply deterministic transitions until external input is required" \
  --until-blocked \
  --apply \
  --input-bundle work/continuation-inputs.json \
  --max-transitions 8 \
  --max-io-bytes 1048576 \
  --out work/continuation-batch-receipt.json
```

All bounded flags, the positive caps, `--lock` and `--out` are mandatory.
`--resume-receipt` is the only optional bounded input. Do not pass singular
operation, projection-guard or transition-input flags: every step comes from
the bundle and is re-projected before the existing one-step transition is
called. The command reserves and incrementally replaces the full receipt;
stdout contains the digest-bound compact summary and never overwrites that
receipt after dispatch.

The batch stops before the next mutation at input, host, model, reviewer,
operator, plan-authority or resource-cap boundaries. Earlier ordinary workflow
events remain committed. Stable invalid-combination codes are
`continuation-batch-apply-required`,
`continuation-batch-arguments-required`, `continuation-batch-cap-invalid`,
`continuation-batch-option-conflict` and
`continuation-one-step-operation-id-required`.

## Inputs

The command accepts only inputs already owned by existing transitions:

- authorization: `--authorization-receipt`;
- task selection/start: `--task`, optionally `--risk-profile`;
- task result: `--result`, `--model-usage-receipt`, `--budget-targets`;
- task review: `--review`, `--implementation-audit`, repeated `--finding-id`;
- final audit outcome: `--final-audit`, `--verdict`, repeated `--task-id` and
  `--finding-id` for `REWORK`;
- finalization: `--final-audit`, `--proof`, `--proof-integrity`,
  `--goal-record`, `--follow-up-register`, `--completion-gate-receipt`,
  `--final-implementation-audit` and repeated `--review-mesh-quorum`.

Every path must be repository-relative. Supplying an input does not make it
trusted: the selected transition still validates canonical form, lineage,
independence, freshness, ownership and policy before mutation.

## Non-mutating routes

Active host work, budget decisions, external actions, unresolved blockers,
terminal runs and `PLAN_ONLY` cannot be advanced by this facade. Their receipts
remain `WAITING` or `BLOCKED` and identify the host- or operator-owned action.
Use the existing command-specific routes for unsupported actions.

Existing `workflow run`, `workflow task-*`, `workflow final-audit-outcome` and
`workflow finalize` commands remain supported. They call the same transition
services and are useful for automation that already knows the exact route.
