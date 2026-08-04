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
