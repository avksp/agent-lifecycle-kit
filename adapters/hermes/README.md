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

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter hermes` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter hermes --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Planning-only launch

The shipped `0.19.0` profile is `UNSUPPORTED` and resolves to
`PLANNING_ONLY_UNSUPPORTED`. A one-shot native tool-denial boundary has not been verified for this contract. Static validation and version
preflight start no model and cannot promote this status. Generic managed launch
remains `WRAPPER_ONLY`.
