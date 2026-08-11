# Claude Code adapter projection

This directory contains the Claude Code projection for Agent Lifecycle Kit. It
is an offline release artifact over the shared lifecycle skills and controller
contract.

Runtime verification is host-specific: Claude Code 2.1.220 has local live
conformance, live calibration and ALK lifecycle proof evidence. This does not
claim public marketplace approval, production promotion or universal host
support.

## Progress bridge

Support level: `WATCH`. Claude Code wrappers can call `agent-lifecycle report
progress-bridge --adapter claude --support-level WATCH --hook-point
side-terminal-watch --state <state>`. Host telemetry remains native; ALK reads
only supplied receipts.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof; it does not claim a native Claude Code progress hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter claude` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter claude --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Event capture

Event capture is declared as `adapter-owned` and uses
`agent-adapter-event.v1` plus `agent-adapter-event-stream-receipt.v1`. See
[Claude Code event bridge](event-bridge.md). Hook configuration belongs to the
operator or adapter; ALK validates the portable event receipt. The support
level remains tied to the accepted Claude Code evidence.
