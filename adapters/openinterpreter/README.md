# OpenInterpreter adapter

OpenInterpreter is represented as a host-local compatible CLI surface with ALK envelopes at the boundary.

Maturity is host-specific `VERIFIED` for `interpreter` 0.0.34 on the tested
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
