# Adapter progress bridge matrix

Progress support is documented separately from adapter maturity. The bridge is
read-only and display-only for every adapter.

| Adapter | Progress support | Hook point | Notes |
| --- | --- | --- | --- |
| Codex | `WATCH` | `side-terminal-watch` | Use a side terminal or wrapper after lifecycle transitions. |
| Claude Code | `WATCH` | `side-terminal-watch` | Host telemetry stays native; ALK reads supplied receipts only. |
| Cursor | `MANUAL` | `manual` | Manual command only while Cursor maturity remains `EXPERIMENTAL`. |
| Gemini CLI | `MANUAL` | `manual` | Manual command only until a wrapper is documented. |
| Goose | `WATCH` | `side-terminal-watch` | ACP remains probe-gated; progress is a local display. |
| Grok Build | `WATCH` | `side-terminal-watch` | Wrapper may call the bridge after Grok-side lifecycle steps. |
| Hermes | `MANUAL` | `manual` | Use the command after ALK workflow transitions. |
| Kimi Code | `MANUAL` | `manual` | Manual command only until live promotion work adds a wrapper. |
| OpenCode | `WATCH` | `side-terminal-watch` | OpenCode adapter keeps host telemetry normalization outside core. |
| OpenInterpreter | `MANUAL` | `manual` | Manual command; provider credentials remain host-local. |
| Pi | `MANUAL` | `manual` | Manual command; provider credentials remain host-local. |
| Qwen Code | `MANUAL` | `manual` | Manual command after lifecycle transitions. |

Common command:

```bash
agent-lifecycle report progress-bridge \
  --adapter <adapter-id> \
  --support-level <AUTO|WATCH|MANUAL|UNSUPPORTED> \
  --hook-point <hook-point> \
  --state <workflow-state.json> \
  --terminal
```

`AUTO` is reserved for adapters with an implemented native hook. `UNSUPPORTED`
means no supported hook or wrapper exists yet. No adapter claims unsupported native hooks from this matrix.
