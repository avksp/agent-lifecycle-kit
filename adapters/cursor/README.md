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

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter cursor` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter cursor --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Planning-only launch

The shipped `2026.07.23` profile is `UNSUPPORTED` and resolves to
`PLANNING_ONLY_UNSUPPORTED`. The CLI does not yet have a verified bounded stdin result transport for this contract. Static validation and version
preflight start no model and cannot promote this status. Generic managed launch
remains `WRAPPER_ONLY`.
