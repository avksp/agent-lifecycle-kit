# Model routing

Model routing selects a provider-neutral model class for lifecycle phases and
task attempts. It does not call provider APIs and does not store concrete model
names in portable plans, task packets, locks, or workflow state.

## Core commands

```bash
agent-lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
agent-lifecycle model profile-check --type host --profile <host-model-profile.json>
agent-lifecycle model route --profile profiles/model-routing-profile.v1.json --host-profile <host-model-profile.json> --request <model-route-request.json>
agent-lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
```

`model route` is deterministic. The same request, routing profile, and optional
host profile produce the same decision digest.

## Model classes

| Class | Purpose |
| --- | --- |
| `no-model` | Deterministic validation, schema checks, context checks and pure file checks. |
| `budget` | Low-risk S0/S1 triage and bounded mechanical work. |
| `local-compact` | Explicit local 4k/8k bounded work only. |
| `standard-code` | Standard S1 implementation and implementation review. |
| `local-standard-code` | Local S0/S1 code work with calibrated JSON, tool-use and context support. |
| `strong-reasoning` | S2 specification, independent review, security/performance/final audit and release gates. |
| `local-strong-review` | Local critical review only after explicit capability, context, usage and calibration gates pass. |
| `specialist-review` | Host-specific specialist reviewer when explicitly configured. |

## Host model profiles

Concrete model names belong in host-local profiles:

```json
{
  "schemaVersion": "agent-lifecycle-host-model-profile.v1",
  "host": "local-host",
  "profileId": "local-host-profile",
  "bindings": {
    "local-strong-review": {
      "providerModel": "<host-specific-local-review-model>",
      "contextWindow": "32k",
      "capabilities": ["text", "json", "tool-use", "deep-review"],
      "jsonReliability": "strict",
      "toolUse": "supported",
      "allowedForTiers": ["S1", "S2"],
      "allowedForPhases": ["independent-review", "security-review", "performance-review", "final-audit"],
      "usageAccounting": "host-attested",
      "dataPolicy": "local-only",
      "calibrationStatus": "PASSED",
      "reviewStrategy": "large-context-or-sliced-review"
    }
  }
}
```

Profile validation redacts provider model names from validation output. The
profile can be untracked or stored in host-specific local configuration.

## Local-only critical review

Local execution is not automatically weak, but small local models are not
automatically review-capable. `local-compact` cannot satisfy final audit,
security review, performance review, production promotion, or S2 independent
review.

If policy is `local-only` and no local binding satisfies the critical review
gates, the lifecycle must block, return `CONDITIONAL`, request human review,
split/refreeze the review scope, or ask for explicit approval to use a stronger
non-local class.

## Policy presets

Use a policy preset instead of asking for a model on every task:

- `cost-optimized`
- `balanced`
- `quality-first`
- `local-only`
- `manual`

Interactive questions are reserved for missing budget limits, data policy,
cloud/local restrictions, or unavailable critical-review capability.

## Usage receipts

Model-backed operations should produce
`agent-lifecycle-model-usage-receipt.v1` with normalized metrics:

- `inputTokens`
- `outputTokens`
- `billableTokens`
- `cumulativeContextBytes`
- `toolCalls`
- `wallSeconds`

`model usage-check` validates host attestation, route binding and budget
ceilings. Missing or unattested usage blocks production promotion evidence.

## Scope boundaries

The v1 implementation is intentionally advisory:

- no provider API clients in core;
- no live price lookup;
- no cross-provider broker;
- no automatic marketplace/model shopping;
- no mandatory per-task questionnaire;
- no prompt-only heuristics without route reason codes.
