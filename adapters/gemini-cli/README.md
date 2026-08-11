# Gemini CLI adapter projection

This directory contains the Gemini CLI projection for Agent Lifecycle Kit. It
declares source-tree metadata, capability hints and host-local receipt
normalization over the shared lifecycle contract.

Gemini CLI remains `EXPERIMENTAL` until live host conformance, usage
calibration and lifecycle proof are accepted for a concrete host range.

## Progress bridge

Support level: `MANUAL`. Use `agent-lifecycle report progress --state <state>
--terminal` after ALK workflow transitions. Progress support remains MANUAL;
native hook ownership stays with the operator or adapter and is covered by the
event bridge contract.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof, not a Gemini CLI native hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter gemini-cli` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter gemini-cli --state <state> --manifest <manifest> --task
<task-id>` binds the session to ALK workflow proof and shows managed progress on stderr
by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Planning-only launch

The shipped `0.46.0` profile is `CANDIDATE` and resolves to
`PLANNING_ONLY_UNSUPPORTED`. The plan approval mode and stdin route form a static candidate, but no accepted live containment evidence is shipped. Static validation and version
preflight start no model and cannot promote this status. Generic managed launch
remains `WRAPPER_ONLY`.
