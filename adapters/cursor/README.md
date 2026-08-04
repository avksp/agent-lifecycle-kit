# Cursor adapter projection

This directory contains the Cursor projection for Agent Lifecycle Kit. It is a
host-specific adapter layer over the shared lifecycle skills and controller
contract.

The adapter maturity is EXPERIMENTAL until a separate live Cursor promotion
suite verifies install, discovery, agent execution, cancellation, usage
attestation, task audit, and final audit.

## Progress bridge

Support level: `MANUAL`. Use `agent-lifecycle report progress --state <state>
--terminal` after ALK workflow transitions. This support level does not promote
Cursor maturity and does not claim unsupported native Cursor hooks.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof, not a Cursor native hook.
