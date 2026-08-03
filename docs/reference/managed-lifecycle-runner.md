# Managed lifecycle runner

`agent-lifecycle workflow run` is a bounded, read-only step-function over a
durable workflow state. It does not launch a model, start a host process or
mutate the workflow state. It verifies the current frozen plan binding and
returns the next host-owned action as a typed receipt.

This closes the gap between the lifecycle skills and the CLI surface: a host
can ask ALK what must happen next without reconstructing the process from chat.

## Command

```bash
agent-lifecycle workflow run \
  --state run.state.json \
  --manifest plans/package/plan.manifest.json \
  --lock plans/package/plan.lock.json \
  --operation-id managed-step-1 \
  --expected-revision 1 \
  --source-revision <git-sha> \
  --out work/run/managed-step-1.json
```

`--lock` is optional when `plan.lock.json` lives next to the manifest.

## Receipt

The command returns `agent-managed-lifecycle-runner-receipt.v1`.

Important fields:

- `status`: `PASS` when the plan/state binding is current; `FAIL` when the
  runner blocks.
- `nextAction`: `agent-managed-lifecycle-next-action.v1`, a compact action for
  the host.
- `modelCallsStarted: false`: the command never starts model work.
- `stateWritten: false`: the command never mutates durable state.
- `hostLaunchStarted: false`: adapters remain responsible for actual launches.
- `blockers`: fail-closed reasons such as stale state revision, non-frozen
  plan, lock mismatch, source revision mismatch, or missing mandatory
  implementation audit reports.

## Boundary with `runner`

`workflow run` is not a replacement for `agent-lifecycle runner
start/status/transition/stop/resume`. The existing runner controls bounded
execution state. The managed lifecycle runner only projects the next lifecycle
step from an already durable workflow state and frozen plan contract.

## No model-call gate

Release validation scans the managed runner modules with
`tools/release/validate_no_model_calls.py`. The gate rejects direct model or
network client imports such as `openai`, `anthropic`, `requests`, `httpx` and
`urllib`.

## Typical host loop

1. Call `workflow run`.
2. Call `report progress --watch` or render one `report progress` projection
   after a lifecycle transition when the host wants a visible status line.
3. If `status` is `FAIL`, surface the typed blocker.
4. If `nextAction.type` is `launch-tasks`, the host launches the listed task
   packets and later records `workflow task-result`.
5. If the plan requires implementation audit, run `agent-lifecycle audit
   implementation` and pass the accepted report to `workflow task-accept`.
6. If `nextAction.type` is `run-final-audit`, run the independent final audit.
7. If `nextAction.type` is `finalize-run`, call `workflow finalize` with the
   accepted final audit and proof path.

The loop remains deterministic because every state mutation still goes through
the existing workflow transition commands with `operation-id`,
`expected-revision` and `source-revision`.

Progress rendering is outside the state transition path. It reads workflow
state, optional host-attested usage receipts and optional change-summary
receipts, so it can be shown in Codex, Claude Code, OpenCode or another host
without adding prompt context.
