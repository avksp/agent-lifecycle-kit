# Codex adapter projection

This directory contains the Codex-native projection for Agent Lifecycle Kit.
It is an offline release artifact, not a separate lifecycle implementation.

The adapter declares how Codex discovers the shared lifecycle skills and how
host-owned operations are mapped to the portable controller contract. Runtime
verification is host-specific: Codex CLI 0.145.0 has local live conformance,
live calibration, and ALK lifecycle proof evidence. This does not claim public
Plugins Directory approval or universal adapter support.

## Progress bridge

Support level: `WATCH`. Codex wrappers can call `agent-lifecycle report
progress-bridge --adapter codex --support-level WATCH --hook-point
side-terminal-watch --state <state>` after ALK lifecycle transitions. The bridge
is read-only, does not start model calls and does not parse Codex telemetry in
core.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof; it does not claim a native Codex progress hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter codex` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter codex --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Event capture

Event capture is declared as `adapter-owned` and uses
`agent-adapter-event.v1` plus `agent-adapter-event-stream-receipt.v1`. See
[Codex event bridge](event-bridge.md). No automatic hook installation is
claimed, and event capture guidance does not change the Codex `VERIFIED`
maturity claim.
