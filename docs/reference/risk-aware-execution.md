# Risk-aware execution

Risk-aware execution turns a frozen plan tier into an explicit model route,
token limit, invocation limit, wall-time limit, and usage-evidence requirement.
It is deterministic and does not call a model or launch an adapter host.
The portable artifact uses the public schema
`agent-risk-execution-profile.v1`.

## Risk levels

`--risk auto` uses the frozen plan tier. An explicit `S0`, `S1`, or `S2` value
may tighten the tier but cannot lower it. The order is `S0 < S1 < S2`.

The default local inputs are:

- `profiles/risk-execution-policy.v1.json` for invocation and wall-time caps;
- `profiles/model-routing-profile.v1.json` for the provider-neutral model class
  and billable-token cap;
- `profiles/lifecycle-baselines.v1.json` for the existing quality floor.

A real S1/S2 managed run also requires `--host-model-profile`. Concrete model
names remain in that local file. The portable risk profile records only the
adapter id, provider-neutral model class, and binding digests.

## Managed start

Use a frozen manifest or a structured run request. This example writes both the
public start receipt and the exact projected risk profile:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode implement \
  --risk auto \
  --file tasks/my-release/plan.manifest.json \
  --state work/my-release/run.state.json \
  --lock tasks/my-release/plan.lock.json \
  --task WS-01 \
  --operation-id start-WS-01-attempt-1 \
  --expected-revision 3 \
  --source-revision "$(git rev-parse HEAD)" \
  --host-model-profile profiles/hosts/codex-live-profile.v1.json \
  --risk-profile-out work/my-release/WS-01/risk-profile.json \
  --out work/my-release/WS-01/start.json
```

`start` remains read-only with respect to workflow state. The returned host
action contains the profile, but the profile has no workflow authority yet and
no model or host process starts.

## Authorize the task attempt

Pass the same artifact to the normal task transition. Use the same operation id
that was bound into the projected route:

```bash
agent-lifecycle workflow task-start \
  --state work/my-release/run.state.json \
  --task WS-01 \
  --operation-id start-WS-01-attempt-1 \
  --expected-revision 3 \
  --source-revision "$(git rev-parse HEAD)" \
  --risk-profile work/my-release/WS-01/risk-profile.json \
  --reason "start risk-aware attempt"
```

This transition validates the profile digest and run, plan, task, source,
adapter, risk-tier, and route lineage. Only then does it store `modelRoute`,
`attemptModelRoute`, and the risk caps in mutable task state. Omitting
`--risk-profile` preserves the legacy task-start path, but that path does not
claim risk-aware execution.

## Usage receipt

For risk-aware S1/S2 attempts, the host-attested model usage receipt must
include the existing normalized metrics plus additive `usage.invocations`:

```json
{
  "usage": {
    "inputTokens": 1200,
    "outputTokens": 300,
    "billableTokens": 1500,
    "cumulativeContextBytes": 24000,
    "toolCalls": 4,
    "wallSeconds": 95,
    "invocations": 2
  },
  "attestation": {
    "source": "host",
    "status": "ATTESTED"
  }
}
```

`workflow task-result` first applies the existing route and attestation checks,
then checks billable tokens, invocations, and wall time against the bound risk
profile. Missing, estimated, lineage-drifted, or over-cap evidence rejects the
transition, so task acceptance remains unreachable.

## Draft boundary

For raw text or Markdown, `--risk` is advisory only:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode plan \
  --risk S2 \
  --file task.md
```

The receipt records the requested recommendation but creates no execution
profile, usage gate, model call, host process, or lifecycle-coverage claim.

## Failure behavior

The command blocks rather than silently weakening policy when:

- an explicit risk is lower than the frozen plan tier;
- a required local policy/profile is missing or invalid;
- the host profile does not match the adapter descriptor host;
- S1/S2 has no host model profile;
- plan, task, source, operation, route, or profile digests do not match;
- host usage is missing, estimated, or above any bound cap.
