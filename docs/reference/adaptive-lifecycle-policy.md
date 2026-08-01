# Adaptive lifecycle policy

Adaptive lifecycle policy selects the lightest safe lifecycle mode from neutral
task inputs. It exists to keep task quality high while avoiding unnecessary
process overhead, especially for small or local models.

The policy uses only portable inputs:

- task shape;
- SDD tier;
- risk flags;
- required evidence;
- prior attempt count;
- context token size;
- resource caps for invocations, wall time and billable tokens.

Provider names, concrete model names, API keys and host auth details must not
enter portable policy requests or decisions. Concrete model binding remains a
host-local routing concern.

## Quality floor

`agent-lifecycle-quality-floor-decision.v1` records the minimum lifecycle mode
that may be selected for the task. Baseline task-shape floors are raised by SDD
tier, risk flags and required evidence. Examples:

- security or S2 work cannot go below `strict`;
- adapter and architecture work cannot go below `strict`;
- release-proof and production-promotion evidence require `release`.

The floor is deterministic and digest-backed. A missing task shape or invalid
baseline fails closed.

## Adaptive decision

Build a decision from an explicit request and the lifecycle baseline profile:

```bash
agent-lifecycle policy adaptive-decision \
  --request <adaptive-request.json> \
  --baseline-profile profiles/lifecycle-baselines.v1.json \
  --out <adaptive-decision.json>
```

Validate an existing decision with:

```bash
agent-lifecycle policy adaptive-check --decision <adaptive-decision.json>
```

Decision receipts use `agent-adaptive-lifecycle-policy-decision.v1`. They carry
the recommended mode, selected mode, quality floor, reason codes, neutral input
summary, request digest and baseline digest.

By default decisions are advisory. Automatic application is allowed only when
the request explicitly sets `automaticSelectionEnabled: true`, the decision has
no blockers, and the selected mode is at or above the quality floor.

Local quality-cost learning can recommend future modes from historical
receipts, but it remains advisory and cannot lower the floor. Low-confidence
signals keep the current or minimum safe mode.

## Resource policy

Optimization is based on tokens and resources, not live currency lookup:

- `resourceBasis` is `tokens-and-resources`;
- `monetaryFieldsUsed` is always `false`;
- monetary metadata is accepted only for `budgetMode: "metered"`;
- local and subscription modes do not need USD fields.

If a metered host reports a nullable or numeric cost field, the policy records
that the metadata existed but does not use it for mode selection. Hard caps and
quality floors still decide whether the lifecycle should continue, pause,
escalate or stay advisory.

## Routing integration

`agent-lifecycle model route` may receive optional `lifecycleMode` and
`qualityFloor` fields. The resolver rejects a request where lifecycle mode is
below the floor. For low-risk S0/S1 work, a `light` lifecycle mode can choose a
budget class route; critical review phases and local-only rules still override
that hint.

Adapters remain responsible for mapping provider-neutral model classes to
host-local model bindings and returning usage receipts.
