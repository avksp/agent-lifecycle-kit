# Adapter progress bridge matrix

Progress support is documented separately from adapter maturity. The bridge is
read-only and display-only for every adapter.

| Adapter | Progress support | ALK-managed hook | Native host hook | Notes |
| --- | --- | --- | --- | --- |
| Codex | `WATCH` | `workflow run/task-result/task-accept/finalize` | Not claimed | Wrapper can opt in with `--progress-hook stderr` or receipt output. |
| Claude Code | `WATCH` | `workflow run/task-result/task-accept/finalize` | Not claimed | Host telemetry stays native; ALK reads supplied receipts only. |
| Cursor | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Not claimed | Manual command only while Cursor maturity remains `EXPERIMENTAL`. |
| Gemini CLI | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Not claimed | Manual command only until a wrapper is documented. |
| Goose | `WATCH` | `workflow run/task-result/task-accept/finalize` | Not claimed | ACP remains probe-gated; progress is a local display. |
| Grok Build | `WATCH` | `workflow run/task-result/task-accept/finalize` | Not claimed | Wrapper may call the bridge after ALK workflow steps. |
| Hermes | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Not claimed | Use the command after ALK workflow transitions. |
| Kimi Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Not claimed | Manual command only until live promotion work adds a wrapper. |
| OpenCode | `WATCH` | `workflow run/task-result/task-accept/finalize` | Not claimed | Host telemetry normalization stays outside core. |
| OpenInterpreter | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Not claimed | Provider credentials remain host-local. |
| Pi | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Not claimed | Provider credentials remain host-local. |
| Qwen Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Not claimed | Manual command after lifecycle transitions. |

Common command:

```bash
agent-lifecycle report progress-bridge \
  --adapter <adapter-id> \
  --support-level <AUTO|WATCH|MANUAL|UNSUPPORTED> \
  --hook-point <hook-point> \
  --state <workflow-state.json> \
  --terminal
```

`AUTO` is reserved for adapters with an implemented ALK-managed wrapper or
native hook plus proof. `UNSUPPORTED` means no supported hook or wrapper exists
yet. No adapter claims unsupported native hooks from this matrix.

ALK-managed hooks are available only when the operator or wrapper runs the
supported ALK workflow commands with `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. A plugin install alone is
not lifecycle proof.
