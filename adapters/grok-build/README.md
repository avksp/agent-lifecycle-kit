# Grok Build adapter

ACP is declared behind a required local probe. A failed probe still leaves operations fail-closed.

Support level is host-specific `VERIFIED` for Grok Build `0.2.117` on the tested
host-local provider/model binding. The live harness uses single-turn JSON output,
disabled subagents/memory/web search, plan permission mode, an empty tools
allowlist and post-invocation clean-worktree checks. Unsupported operations
fail closed and lifecycle semantics stay delegated to ALK core.

## Progress bridge

Support level: `WATCH`. Grok Build wrappers can call `agent-lifecycle report
progress-bridge --adapter grok-build --support-level WATCH --hook-point
side-terminal-watch --state <state>` after host-side lifecycle steps. The ACP
path remains probe-gated, and ALK does not parse Grok-specific telemetry in core.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof; it does not claim a native Grok Build progress hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter grok-build` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter grok-build --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Planning-only launch

The shipped `0.2.118` profile is `UNSUPPORTED` and resolves to
`PLANNING_ONLY_UNSUPPORTED`. The CLI does not yet have a verified bounded stdin result transport for this contract. Static validation and version
preflight start no model and cannot promote this status. Generic managed launch
remains `WRAPPER_ONLY`.
