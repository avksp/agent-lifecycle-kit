# Controlled runner

The runner is a provider-neutral execution-loop controller. It records a narrow
state for task attempts, validations, reviews, remediation, reroutes, splits,
blocks, stops and resumes.

The runner does not replace workflow state. Workflow state remains
authoritative for lifecycle phase, task acceptance, blockers and final proof.
Runner state only preserves the bounded loop around those workflow primitives.

## Commands

```bash
agent-lifecycle runner start --state <run.state.json> --runner <runner.state.json> --operation-id <id> --reason "<reason>"
agent-lifecycle runner status --runner <runner.state.json> --state <run.state.json>
agent-lifecycle runner status --runner <runner.state.json> --state <run.state.json> --profile profiles/small-context-profile.v1.json --target-window 4k-strict
agent-lifecycle runner transition --runner <runner.state.json> --state <run.state.json> --request <runner-transition-request.json>
agent-lifecycle runner stop --runner <runner.state.json> --state <run.state.json> --operation-id <id> --expected-runner-revision <n> --reason "<reason>"
agent-lifecycle runner resume --runner <runner.state.json> --state <run.state.json> --operation-id <id> --expected-runner-revision <n> --reason "<reason>"
```

## Transition request

Transitions are described by `agent-runner-transition-request.v1` documents.

```json
{
  "schemaVersion": "agent-runner-transition-request.v1",
  "operationId": "attempt-1",
  "expectedRunnerRevision": 1,
  "action": "attempt",
  "taskId": "WS-01",
  "reason": "Start the next bounded attempt"
}
```

Supported actions are `attempt`, `validate`, `review`, `accept`, `remediate`,
`reroute`, `split`, `block` and `abort`.

## Resource guards

`agent-runner-policy.v1` bounds attempts, reroutes, splits and billable tokens.
The runner rejects transitions that would exceed these caps before writing
state.

Remediation patch metadata is accepted only when the patch reports `PASS`, has
a digest and every changed file is inside the task write scope from workflow
state. The runner validates this metadata; it does not apply patches itself.

Attempt transitions may include an `isolationReceipt`. When present, the
runner validates `agent-worktree-attempt-receipt.v1` and records the receipt
digest in transition history.

## Small and large models

`agent-runner-snapshot.v1` is a compact status view for continuation prompts.
It fits the selected small-context profile or fails closed. Small local models
can use it to continue without replaying long history. Larger models can still
inspect full runner state, workflow state, evidence, reviews and audits for
quality-sensitive decisions.
