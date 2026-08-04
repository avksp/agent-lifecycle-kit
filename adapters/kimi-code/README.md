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
