# Goose Adapter

This adapter is a host-specific `VERIFIED` Agent Lifecycle Kit projection for
Goose `1.45.0`. It declares ACP as a neutral host capability and keeps
lifecycle semantics in ALK core.

The promotion evidence is bounded to no-session, no-profile Goose invocations
with explicit host-local provider/model selection. A supported ACP declaration
still requires a host probe before use; missing executable, failed probe, or
invalid invocation contract must fail closed.

This adapter does not claim public directory approval, production platform
promotion, universal ACP support, or verified OS sandbox containment.

## Progress bridge

Support level: `WATCH`. Goose wrappers can call `agent-lifecycle report
progress-bridge --adapter goose --support-level WATCH --hook-point
side-terminal-watch --state <state>`. This is a local read-only display; ACP
support remains separately probe-gated.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof; it does not claim a native Goose progress hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter goose` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter goose --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.
