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
