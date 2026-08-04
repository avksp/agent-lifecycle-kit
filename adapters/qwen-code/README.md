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
