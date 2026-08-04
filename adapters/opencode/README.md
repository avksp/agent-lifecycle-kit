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
