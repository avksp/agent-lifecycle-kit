# Managed adapter session support

Managed session support is a separate dimension of the adapter support level and
progress support.
It describes whether ALK can create a managed session receipt and whether the
adapter descriptor declares a safe native launch profile.
The main [adapter support matrix](support-matrix.md) surfaces the current
`managedLaunch.status` value; this page explains the boundary.

| Adapter | Managed session | Native launch profile | Notes |
| --- | --- | --- | --- |
| Codex | Supported | `WRAPPER_ONLY` | Use `adapter task start`, `adapter run` or a host wrapper for lifecycle proof. |
| Claude Code | Supported | `WRAPPER_ONLY` | Native launch remains host-owned. |
| Cursor | Supported | `WRAPPER_ONLY` | Lifecycle proof uses the managed ALK route. |
| Gemini CLI | Supported | `WRAPPER_ONLY` | Use the verified ALK route for a bound process. |
| Goose | Supported | `WRAPPER_ONLY` | ACP remains separately probe-gated. |
| Grok Build | Supported | `WRAPPER_ONLY` | Native provider/model handling stays host-local. |
| Hermes | Supported | `WRAPPER_ONLY` | Use managed ALK commands for lifecycle proof. |
| Kimi Code | Supported | `WRAPPER_ONLY` | Lifecycle proof uses the managed ALK route. |
| OpenCode | Supported | `WRAPPER_ONLY` | Host telemetry stays outside core. |
| OpenInterpreter | Supported | `WRAPPER_ONLY` | Provider credentials stay host-local. |
| Pi | Supported | `WRAPPER_ONLY` | Provider credentials stay host-local. |
| Qwen Code | Supported | `WRAPPER_ONLY` | Lifecycle proof requires managed ALK command use. |

Common task intake command:

```bash
agent-lifecycle adapter task start \
  --adapter <adapter-id> \
  --file task.md
```

Raw text and Markdown return review-gated draft intake. To start managed work
immediately, pass a frozen `agent-adapter-task-run-request.v1` file or a frozen
manifest plus workflow binding flags.

Common managed run command:

```bash
agent-lifecycle adapter run \
  --adapter <adapter-id> \
  --state <workflow-state.json> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --task <task-id>
```

`WRAPPER_ONLY` means ALK binds a session to workflow proof and renders progress
from ALK state through managed commands or a reviewed wrapper. Verified local
profiles describe the process route for adapters with accepted launch evidence.
Plugin installation and lifecycle proof are separate records.
