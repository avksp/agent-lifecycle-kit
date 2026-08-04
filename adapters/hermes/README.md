# Hermes adapter projection

This directory contains the Hermes projection for Agent Lifecycle Kit. It
describes skill-directory discovery, optional slash-command invocation, and
host operation mapping for the shared lifecycle controller contract.

The adapter is host-specific `VERIFIED` for Hermes Agent `v0.19.0` in the current
source tree. The claim is bounded to the committed live evidence and does not
claim publication or production-platform promotion.

## Progress bridge

Support level: `MANUAL`. Use `agent-lifecycle report progress --state <state>
--terminal` after ALK workflow transitions. The bridge is read-only and does
not start host or model work.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof, not a Hermes native hook.
