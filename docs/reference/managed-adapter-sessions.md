# Managed adapter sessions

Managed adapter sessions give operators one ALK entrypoint for adapter-backed
work without making ALK a second coding-agent runtime.

The simplest entrypoint is `agent-lifecycle start`. It selects task intake,
explicit frozen-run delegation or stored-session resume while preserving the
same lower-level contracts.

There are three operator-facing modes:

- interactive session: `adapter session start --adapter <id>` records a
  session and returns `WAITING_FOR_TASK`; it does not claim lifecycle coverage;
- task intake: `adapter task start --adapter <id> --file task.md` or
  `--text "..."` creates reviewed draft intake. It can recommend the optional
  Bug Forensics profile for defect-shaped tasks or an analysis-first workstream
  for inspection-first tasks. It also includes advisory Review Mesh
  recommendation when extra reviewers may improve planning, research or audit
  quality, but raw input never starts execution;
- managed run: `adapter run --adapter <id> --state <state> --manifest
  <manifest> --task <task-id>` binds the session to a frozen workflow state and
  returns the next ALK-owned lifecycle action.

Resume is lineage-checked. `adapter session resume` compares the stored session
with the requested adapter, workflow state and task id. A mismatch returns
`agent-adapter-session-resume-receipt.v1` with `status: BLOCKED`.

## Commands

```bash
agent-lifecycle start --adapter codex --file task.md
agent-lifecycle start --adapter codex --mode research --text "Inspect the current design"
agent-lifecycle start --adapter codex --mode plan --file task.md --launch
agent-lifecycle start --adapter codex --mode implement --file adapter-run-request.json
agent-lifecycle start --adapter codex --resume <session-id>
agent-lifecycle host-launch inspect --profile .alk/host-launch/codex.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/codex.json
agent-lifecycle adapter launch-profile --adapter codex --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/codex.json

agent-lifecycle adapter session start --adapter codex
agent-lifecycle adapter session start --adapter codex --launch
agent-lifecycle adapter session status --session <session-id>
agent-lifecycle adapter session promote \
  --session <session-id> \
  --state <workflow-state.json> \
  --task <task-id>
agent-lifecycle adapter session resume \
  --session <session-id> \
  --state <workflow-state.json> \
  --task <task-id>
agent-lifecycle adapter task start --adapter codex --file task.md
agent-lifecycle adapter task start --adapter codex --task-text "Fix the regression"
agent-lifecycle adapter task start --adapter codex --file adapter-run-request.json
agent-lifecycle adapter run \
  --adapter codex \
  --state <workflow-state.json> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --task <task-id>
```

Raw planning input may add `--launch` only when the profile's exact-version
planning status is `PLANNING_ONLY_QUALIFIED`; it ends at review and stores
digest-only state. Current shipped candidates remain unsupported. See
[Planning-only adapter launch](planning-only-launch.md).

An operator-local frozen implementation launch adds `--launch --host-launch-profile
.alk/host-launch/<adapter>.json` to the fully bound `start --mode implement`
command. See [Local host launch](local-host-launch.md) for the profile and the
complete command. Raw input never reaches this implementation route.

For the exact Codex, Claude Code and OpenCode versions verified by ALK, use
the generated profile and mandatory version receipt from [Frozen-task launch
through a verified profile](qualified-host-launch.md).

`start` emits `agent-lifecycle-start-receipt.v1`. Its nested delegate summary
contains only stable status, advisory and receipt-digest fields; it excludes
raw task text and local absolute paths. `auto`, `research`, `plan` and `review`
are non-executing. `implement` delegates only a complete structured frozen
request. Resume accepts only a session stored by ALK, checks adapter and state
lineage, and never attaches to a native host conversation.

`adapter task start` emits `agent-adapter-task-start-receipt.v1`. For raw text
or Markdown, the receipt stores only source label, digest and byte count, not
the raw task text. The `reviewMeshRecommendation` field is advisory and cannot
activate blocking review by itself. Use `--candidate-out <path>` when the draft
planning import artifact should be persisted.

`adapter run`, `adapter task start` on the frozen-run path, and `adapter
session promote` enable terminal progress on stderr by default because they are
ALK-managed paths. JSON stdout remains stable. Use `--progress-hook off` to
suppress terminal output, or `--progress-hook receipt --progress-receipt <path>`
to persist `agent-progress-hook-receipt.v1`.

## Risk-aware managed execution

For a frozen S1/S2 task, `start --risk auto` can derive a provider-neutral
model route and token, invocation, and wall-time caps. This is a two-step
authorization: `start --risk-profile-out <path>` only projects a read-only,
digest-bound profile; `workflow task-start --risk-profile <path>` validates and
stores that profile before the attempt begins. The later `workflow task-result`
must provide host-attested usage, including `usage.invocations`.

Raw text and Markdown remain draft-only: `--risk` is advisory there and cannot
enable execution or a usage gate. See [Risk-aware
execution](risk-aware-execution.md) for the full command sequence and failure
rules.

## Launch profile

The adapter descriptor field `managedLaunch` declares one of the following
profiles. It is descriptive data, not generic process-execution authority:

| Status | Meaning |
| --- | --- |
| `SUPPORTED` | The descriptor may supply argv templates for a separately verified local route. The generic library and CLI route do not execute them. |
| `WRAPPER_ONLY` | A wrapper or operator flow can use ALK managed sessions, but native argv launch is not claimed. |
| `UNSUPPORTED` | No managed launch route is declared. |

Current bundled adapters declare `WRAPPER_ONLY`. That keeps lifecycle proof
available through ALK-managed commands without claiming unsupported native host
hooks or command lines. A validated operator-local profile can explicitly start
one process after frozen and risk bindings pass, but that local fact does not
change the public support claim. `adapter session start --launch` and direct generic
descriptor launch both return `adapter-generic-launch-disabled` before process
creation, regardless of the declared profile status.

## Security boundary

Managed adapter sessions are fail-closed and display-safe:

- launch uses argv arrays with `shell: false`;
- generic environment selection accepts exact names only; wildcard patterns are
  rejected;
- provider secrets are selected only from descriptor/project allowlists;
- shared redaction removes tested secret and local-path forms from receipts and
  records whether a stored value changed;
- tracked native host config files are not written;
- ALK does not inject prompts into host CLIs;
- ALK does not parse host-specific telemetry in core;
- plugin installation alone is not managed lifecycle proof.

The stable receipts are `agent-adapter-session-receipt.v1`,
`agent-managed-adapter-launch-receipt.v1`,
`agent-adapter-session-resume-receipt.v1`,
`agent-adapter-task-start-receipt.v1`,
`agent-adapter-task-run-request.v1`, `agent-lifecycle-start-receipt.v1` and
`agent-local-host-launch-profile-receipt.v1`.
Review Mesh recommendations use
`agent-review-mesh-recommendation.v1`.

For long managed sessions, [context checkpoints](context-checkpoints.md) can
preserve a bounded continuity view. Session lineage and checkpoint lineage are
separate: restoring context never reattaches to a native host conversation and
never grants implementation authority.
