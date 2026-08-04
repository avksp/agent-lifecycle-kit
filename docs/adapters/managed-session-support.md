# Managed adapter session support

Managed session support is separate from adapter maturity and progress support.
It describes whether ALK can create a managed session receipt and whether the
adapter descriptor declares a safe native launch profile.

| Adapter | Managed session | Native launch profile | Notes |
| --- | --- | --- | --- |
| Codex | Supported | `WRAPPER_ONLY` | Use `adapter run` or a host wrapper for lifecycle proof. |
| Claude Code | Supported | `WRAPPER_ONLY` | Native launch remains host-owned. |
| Cursor | Supported | `WRAPPER_ONLY` | Does not change Cursor maturity. |
| Gemini CLI | Supported | `WRAPPER_ONLY` | No native argv launch claim. |
| Goose | Supported | `WRAPPER_ONLY` | ACP remains separately probe-gated. |
| Grok Build | Supported | `WRAPPER_ONLY` | Native provider/model handling stays host-local. |
| Hermes | Supported | `WRAPPER_ONLY` | Skill install alone is not lifecycle proof. |
| Kimi Code | Supported | `WRAPPER_ONLY` | Does not change Kimi maturity. |
| OpenCode | Supported | `WRAPPER_ONLY` | Host telemetry stays outside core. |
| OpenInterpreter | Supported | `WRAPPER_ONLY` | Provider credentials stay host-local. |
| Pi | Supported | `WRAPPER_ONLY` | Provider credentials stay host-local. |
| Qwen Code | Supported | `WRAPPER_ONLY` | Lifecycle proof requires managed ALK command use. |

Common managed command:

```bash
agent-lifecycle adapter run \
  --adapter <adapter-id> \
  --state <workflow-state.json> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --task <task-id>
```

`WRAPPER_ONLY` means ALK can bind a session to workflow proof and render
progress from ALK state, but it does not claim that core ALK can safely spawn
the native host CLI for that adapter.

This does not claim safe native argv launch, and plugin installation is not
lifecycle proof.
