# OpenInterpreter adapter

OpenInterpreter is represented as a host-local compatible CLI surface with ALK envelopes at the boundary.

Support level is host-specific `VERIFIED` for `interpreter` 0.0.34 on the tested
host-local provider/model binding. The bounded JSONL live harness uses
`interpreter exec` with ephemeral read-only invocation, no approval prompts and
post-invocation clean-worktree checks. The selected provider's key must come
from OpenInterpreter's normal credential source; ALK can scope a private env
file to the harness process only with an explicit `--host-env-allow` variable
name. Unsupported operations fail closed and lifecycle semantics stay delegated
to ALK core.

## Progress bridge

Support level: `MANUAL`. Use `agent-lifecycle report progress --state <state>
--terminal` after ALK workflow transitions. Provider credentials and telemetry
remain outside ALK core.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof, not an OpenInterpreter native hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter openinterpreter` records an interactive session without lifecycle coverage.
`agent-lifecycle adapter run --adapter openinterpreter --state <state> --manifest
<manifest> --task <task-id>` binds the session to ALK workflow proof and shows managed
progress on stderr by default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Planning-only launch

The shipped `0.0.34` profile is `UNSUPPORTED` and resolves to
`PLANNING_ONLY_UNSUPPORTED`. The installed command surface does not expose a reliable native read-only profile. Static validation and version
preflight start no model and cannot promote this status. Generic managed launch
remains `WRAPPER_ONLY`.
