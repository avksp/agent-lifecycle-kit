# Budget Reroute Policy

Budget caps are safety guards, not task-completion criteria. If a model-backed
attempt exceeds a route, token, wall-clock, invocation, or metered spend cap, the
workflow must keep the task incomplete and record a budget decision before any
new model invocation starts.

## Modes

`agent-lifecycle-budget-exceeded-policy.v1` supports two decision modes:

- `manual`: pause in `WAITING_FOR_BUDGET_DECISION` and expose allowed operator
  actions.
- `auto`: choose one bounded action deterministically from the policy.

Budget accounting supports three resource modes:

- `metered`: requires a positive `budgetCapUsd`.
- `subscription`: requires `maxInvocations` plus at least one of
  `maxBillableTokens` or `maxWallSeconds`.
- `local`: uses the same resource caps as `subscription`, but does not require
  a USD cap.

## Manual Pause

```bash
agent-lifecycle workflow budget-decision \
  --state work/<run>/workflow/run.state.json \
  --task WS-01 \
  --operation-id budget-decision-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <git-sha> \
  --model-usage-receipt work/WS-01/attempt-1/model-usage-receipt.json \
  --budget-policy policies/budget-exceeded-policy.json \
  --receipt work/WS-01/attempt-1/budget-decision.json \
  --reason "route token cap exceeded"
```

The command writes `agent-lifecycle-budget-decision-receipt.v1`, moves the run
to `WAITING_FOR_BUDGET_DECISION`, and sets `blocker.code` to
`BUDGET_DECISION_REQUIRED`.

## Apply A Decision

```bash
agent-lifecycle workflow budget-decision \
  --state work/<run>/workflow/run.state.json \
  --task WS-01 \
  --operation-id budget-apply-WS-01-attempt-1 \
  --expected-revision 8 \
  --source-revision <git-sha> \
  --action reroute-stronger \
  --decision-receipt work/WS-01/attempt-1/budget-decision.json \
  --route-decision work/WS-01/attempt-1/reroute-decision.json \
  --receipt work/WS-01/attempt-1/budget-decision-applied.json \
  --operator-identity-hash <redacted-operator-hash> \
  --reason "operator selected stronger route"
```

The applied receipt is a second immutable
`agent-lifecycle-budget-decision-receipt.v1` artifact. It binds the pending
decision receipt, selected action, operator identity for manual mode, and either
the next route decision, split packet identity, or explicit cap deltas.

## Critical Reviews

Critical review phases must not automatically downgrade to `budget` or
`local-compact`. If `forbidDowngradeForCriticalReview` is true and the default
auto action is a cheaper reroute, the controller selects a stronger route,
splits the task, continues the same route, or aborts according to the allowed
actions.

## Local Configuration

Concrete provider names, subscription tiers, local model names, and personal
limits belong in host-local policy files or live evidence. Portable plans and
workflow state should carry neutral actions, redacted model hashes, and policy
digests.
