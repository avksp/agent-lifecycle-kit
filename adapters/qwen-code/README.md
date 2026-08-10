# Qwen Code adapter projection

This directory contains the Qwen Code projection for Agent Lifecycle Kit. It
declares source-tree metadata, capability hints and host-local receipt
normalization over the shared lifecycle contract.

Qwen Code `0.21.0` has host-specific `VERIFIED` evidence for the tested
host-local provider/model binding. This does not claim public directory
approval, production promotion or universal provider support.

## Progress bridge

Support level: `MANUAL`. Use `agent-lifecycle report progress --state <state>
--terminal` after ALK workflow transitions. The bridge is read-only and does
not parse Qwen-specific telemetry in core.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof, not a Qwen Code native hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter qwen-code` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter qwen-code --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Planning-only launch

The shipped `0.21.8` profile is `UNSUPPORTED` and resolves to
`PLANNING_ONLY_UNSUPPORTED`. A native read-only or tool-denial boundary has not been verified for this contract. Static validation and version
preflight start no model and cannot promote this status. Generic managed launch
remains `WRAPPER_ONLY`.
