# Adapter progress bridge matrix

Progress support is a separate dimension of the adapter support level. The
bridge is read-only and display-only for every adapter.

| Adapter | Progress support | ALK-managed hook | Native host route | Notes |
| --- | --- | --- | --- | --- |
| Codex | `WATCH` | `workflow run/task-result/task-accept/finalize` | Host-side | Wrapper can opt in with `--progress-hook stderr` or receipt output. |
| Claude Code | `WATCH` | `workflow run/task-result/task-accept/finalize` | Host-side | Host telemetry stays native; ALK reads supplied receipts only. |
| Cursor | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Host-side | Use the progress command after ALK workflow transitions. |
| Gemini CLI | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Host-side | Use the progress command after ALK workflow transitions. |
| Goose | `WATCH` | `workflow run/task-result/task-accept/finalize` | Host-side | ACP remains probe-gated; progress is a local display. |
| Grok Build | `WATCH` | `workflow run/task-result/task-accept/finalize` | Host-side | Wrapper may call the bridge after ALK workflow steps. |
| Hermes | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Host-side | Use the command after ALK workflow transitions. |
| Kimi Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Host-side | Use the progress command after ALK workflow transitions. |
| OpenCode | `WATCH` | `workflow run/task-result/task-accept/finalize` | Host-side | Host telemetry normalization stays outside core. |
| OpenInterpreter | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Host-side | Provider credentials remain host-local. |
| Pi | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Host-side | Provider credentials remain host-local. |
| Qwen Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Host-side | Manual command after lifecycle transitions. |

Common command:

```bash
agent-lifecycle report progress-bridge \
  --adapter <adapter-id> \
  --support-level <AUTO|WATCH|MANUAL|UNSUPPORTED> \
  --hook-point <hook-point> \
  --state <workflow-state.json> \
  --terminal
```

`AUTO` is used when an adapter has an implemented ALK-managed wrapper or native
hook with proof. `UNSUPPORTED` marks an adapter whose supported hook route is
still being qualified. The matrix reports the exact route for every adapter.

ALK-managed hooks are available when the operator or wrapper runs the supported
ALK workflow commands with `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. A plugin install alone is
one input to the route; lifecycle proof comes from the resulting ALK receipts.
