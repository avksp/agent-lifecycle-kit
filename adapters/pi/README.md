# Pi adapter

This projection uses RPC/JSON plus AGENTS/agentskills metadata. The alternate protocol capability is not claimed.

Maturity is host-specific `VERIFIED` for Pi 0.83.0 on the tested host-local
provider/model binding. Live host conformance, usage receipts, host-env hygiene
and lifecycle proof are recorded in
`docs/adapters/evidence/pi-live-verified.md`.

The adapter does not claim ACP support, public directory approval, production
promotion, or sandbox containment beyond the bounded no-tools/no-session/no
project-context live harness policy. Unsupported operations fail closed and
lifecycle semantics stay delegated to ALK core.

## Progress bridge

Support level: `MANUAL`. Use `agent-lifecycle report progress --state <state>
--terminal` after ALK workflow transitions. Provider credentials and telemetry
remain outside ALK core.

ALK-managed workflow commands can also use `--progress-hook stderr` or
`--progress-hook receipt --progress-receipt <path>`. This records managed
workflow proof, not a Pi native hook.

## Managed adapter sessions
Managed session support: `WRAPPER_ONLY`. `agent-lifecycle adapter session start
--adapter pi` records an interactive session without lifecycle coverage. `agent-
lifecycle adapter run --adapter pi --state <state> --manifest <manifest> --task <task-
id>` binds the session to ALK workflow proof and shows managed progress on stderr by
default.

The descriptor does not claim safe native argv launch for this host CLI. Provider
credentials, native launch, waits, cancellation and telemetry remain host-owned.

## Planning-only launch

The shipped `0.83.0` profile is `UNSUPPORTED` and resolves to
`PLANNING_ONLY_UNSUPPORTED`. The read-only tool list exists, but bounded stdin result transport has not been verified. Static validation and version
preflight start no model and cannot promote this status. Generic managed launch
remains `WRAPPER_ONLY`.
