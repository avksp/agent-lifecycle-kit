# Kimi Code adapter projection

This directory contains the Kimi Code projection for Agent Lifecycle Kit. It
declares source-tree metadata, capability hints and host-local receipt
normalization over the shared lifecycle contract.

Kimi Code remains `EXPERIMENTAL` until provider/model configuration, live host
conformance, usage calibration and lifecycle proof are accepted.

## Progress bridge

Support level: `MANUAL`. Use `agent-lifecycle report progress --state <state>
--terminal` after ALK workflow transitions. This does not change adapter
maturity and does not claim unsupported native Kimi Code hooks.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof, not a Kimi Code native hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter kimi-code` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter kimi-code --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.
