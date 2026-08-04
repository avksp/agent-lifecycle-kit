# OpenCode adapter projection

This directory contains the OpenCode projection for Agent Lifecycle Kit. The
JavaScript file is a launcher metadata shim; lifecycle semantics remain in the
shared controller and skills.

The adapter is host-specific `VERIFIED` for OpenCode CLI `1.18.9` in the current
source tree. The claim is bounded to the committed live evidence and does not
claim npm publication or production-platform promotion.

## Progress bridge

Support level: `WATCH`. OpenCode wrappers can call `agent-lifecycle report
progress-bridge --adapter opencode --support-level WATCH --hook-point
side-terminal-watch --state <state>`. OpenCode-specific telemetry
normalization stays outside ALK core.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof; it does not claim a native OpenCode progress hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter opencode` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter opencode --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.
