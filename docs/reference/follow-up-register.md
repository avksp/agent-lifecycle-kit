# Follow-up register

The follow-up register is a schema-backed record for work that is explicitly
outside the current scope, blocked by external action, or scheduled after an
accepted tradeoff. It is not accepted evidence by itself.

Each `agent-follow-up-register.v1` item carries:

- source trace: requirement, acceptance or evidence ids, plus an out-of-scope
  reason or external blocker;
- owner and current status;
- target release or blocker;
- closure evidence requirements;
- optional current-scope impact.

Open items with `currentScopeImpact` set to `current-acceptance` or
`completion-proof` make finalization fail closed; the check fails closed before
writing final proof. Closed items must bind
required evidence ids and current artifact identities.

## Commands

```bash
agent-lifecycle followup check --register <follow-up-register.json> --state <run.state.json> --fail-on-finalization-blockers
agent-lifecycle followup add --register <follow-up-register.json> --item <follow-up-item.json>
agent-lifecycle followup close --register <follow-up-register.json> --item-id <id> --evidence-id <evidence-id> --artifact <path> --verifier <id> --reason "<reason>"
agent-lifecycle followup sweep --register <follow-up-register.json> --state <run.state.json> --profile profiles/small-context-profile.v1.json --target-window 4k-strict
```

`agent-follow-up-summary.v1` is the compact continuation view. It includes
counts, open items and finalization blockers, and must fit the selected
small-context profile. Larger models can inspect the full register, closure
artifacts, final audit and proof.

`workflow finalize` can bind a checked register into final proof with
`--follow-up-register <follow-up-register.json>`.
