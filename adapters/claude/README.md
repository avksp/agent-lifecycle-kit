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
