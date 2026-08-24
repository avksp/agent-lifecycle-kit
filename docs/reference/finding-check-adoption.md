# Finding-to-check adoption

Release 1.86 connects an accepted review finding to a deterministic check. It
does not create a second finding registry, execute a command from a receipt or
grant an implementation permission.

## Contract

The binding contract is `agent-finding-check-binding.v1`. A binding records:

- the finding ID and digest;
- the passing plan delta and its package, revision, digest and source revision;
- a symbolic check identity (`id`, `route` and its digest);
- owner, bounded scope, source revision and expected result;
- an authorized transition history.

The check identity is deliberately not an executable command. It cannot contain
`shell`, `exec`, `script`, `argv` or command text. An existing release or project
validation route remains responsible for deciding how a check is executed.

## Lifecycle

The only allowed order is:

```text
PROPOSED -> ACCEPTED -> IMPLEMENTED -> VERIFIED -> RETIRED
```

Every transition requires an explicit approved authorization with an actor and
operation ID. Repeating the same transition with the same operation ID is
idempotent; a different operation ID is rejected. `IMPLEMENTED` and `VERIFIED`
require read-only evidence. `VERIFIED` also requires the evidence result to
match the expected result.

Proposals are advisory: they always carry `approvalRequired: true`,
`applyAllowed: false` and `authorityClaimed: false`. They cannot lower a plan,
replace an independent audit or mark production promotion.

## CLI flow

The inputs below are JSON artifacts. ALK reads them and writes a new artifact;
it does not start a model, host process or arbitrary shell command.

1. Build a plan delta and prepare a finding, check identity and scope.

   ```bash
   agent-lifecycle plan delta \
     --before plan-before.json --after plan-after.json --out plan-delta.json
   agent-lifecycle plan finding-check propose \
     --finding finding.json --delta plan-delta.json \
     --check check-identity.json --scope check-scope.json \
     --owner WS86-01 --source-revision "$SOURCE_REVISION" \
     --out finding-check-proposal.json
   ```

   `check-identity.json` contains only `{"id": "...", "route": "..."}`.
   The route names an existing validation route; it is not a shell command.

2. Validate the advisory proposal. A passing result still requires explicit
   authorization.

   ```bash
   agent-lifecycle plan finding-check validate \
     --proposal finding-check-proposal.json
   agent-lifecycle plan finding-check accept \
     --proposal finding-check-proposal.json \
     --authorization approved-operation.json \
     --out accepted-transition.json
   ```

   The acceptance command returns a transition receipt. Use its `binding`
   member as the binding artifact for the next steps.

3. Produce read-only evidence from the existing check route and bind it to the
   accepted source revision.

   ```bash
   jq '.binding' accepted-transition.json > accepted-binding.json
   agent-lifecycle plan finding-check evidence \
     --binding accepted-binding.json --result PASS \
     --source-revision "$SOURCE_REVISION" \
     --evidence-id EV86-CHECK --out finding-check-evidence.json
   agent-lifecycle plan finding-check transition \
     --binding accepted-binding.json --target-status IMPLEMENTED \
     --authorization implemented-operation.json \
     --evidence finding-check-evidence.json --out implemented-transition.json
   ```

   The same evidence is supplied for the `VERIFIED` transition after the check
   has produced its final result. A changed source revision, check identity,
   finding, plan delta or evidence digest fails closed.

## Security and authority boundaries

Finding adoption is a traceability mechanism, not an execution engine. It keeps
the following guarantees:

- the plan delta must already pass validation and remain lineage-compatible;
- an orphan, stale or retired binding cannot be active;
- evidence is explicitly read-only and records zero model or host launches;
- a receipt cannot claim production promotion or independent reviewer authority;
- existing security, architecture, quality and publication gates remain
  mandatory and are not replaced by a finding-check result.

For the complete public schema surface, see [Public contracts](public-contracts.md).
