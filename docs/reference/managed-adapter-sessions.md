# Managed adapter sessions

Managed adapter sessions give operators one ALK entrypoint for adapter-backed
work without making ALK a second coding-agent runtime.

There are two modes:

- interactive session: `adapter session start --adapter <id>` records a
  session and returns `WAITING_FOR_TASK`; it does not claim lifecycle coverage;
- managed run: `adapter run --adapter <id> --state <state> --manifest
  <manifest> --task <task-id>` binds the session to a frozen workflow state and
  returns the next ALK-owned lifecycle action.

Resume is lineage-checked. `adapter session resume` compares the stored session
with the requested adapter, workflow state and task id. A mismatch returns
`agent-adapter-session-resume-receipt.v1` with `status: BLOCKED`.

## Commands

```bash
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
agent-lifecycle adapter run \
  --adapter codex \
  --state <workflow-state.json> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --task <task-id>
```

`adapter run` and `adapter session promote` enable terminal progress on stderr
by default because they are ALK-managed paths. JSON stdout remains stable. Use
`--progress-hook off` to suppress terminal output, or `--progress-hook receipt
--progress-receipt <path>` to persist `agent-progress-hook-receipt.v1`.

## Launch profile

Native launch is descriptor-driven. The adapter descriptor field
`managedLaunch` declares one of:

| Status | Meaning |
| --- | --- |
| `SUPPORTED` | The descriptor supplies safe argv templates for managed launch. |
| `WRAPPER_ONLY` | A wrapper or operator flow can use ALK managed sessions, but native argv launch is not claimed. |
| `UNSUPPORTED` | No managed launch route is declared. |

Current bundled adapters declare `WRAPPER_ONLY`. That keeps lifecycle proof
available through ALK-managed commands without claiming unsupported native host
hooks or command lines.

## Security boundary

Managed adapter sessions are fail-closed and display-safe:

- launch uses argv arrays with `shell: false`;
- provider secrets are selected only from descriptor/project allowlists;
- secret values are redacted from receipts;
- tracked native host config files are not written;
- ALK does not inject prompts into host CLIs;
- ALK does not parse host-specific telemetry in core;
- plugin installation alone is not managed lifecycle proof.

The stable receipts are `agent-adapter-session-receipt.v1`,
`agent-managed-adapter-launch-receipt.v1` and
`agent-adapter-session-resume-receipt.v1`.
