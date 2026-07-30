# Public Contracts

Public contract policy keeps ALK outputs predictable for adapters, release
checks and operator scripts.

`agent-public-contract-policy.v1` lists the current public schemas, CLI JSON
outputs and compatibility rules. The policy is generated from the bundled
schema registry, so it is small enough for compact review and still points to
the authoritative full schemas.

```bash
agent-lifecycle contract policy --out <public-contract-policy.json>
agent-lifecycle contract check --policy <public-contract-policy.json>
```

The compatibility rules are intentionally narrow:

- public schema ids are immutable;
- existing required fields must not change meaning in-place;
- compatible additions use optional fields or a new schema id;
- deprecated input shapes remain accepted until a replacement is documented;
- CLI commands keep compact JSON envelopes with stable `schemaVersion` values;
- failures use `agent-lifecycle-error.v1` with a stable `code`.

Adapters should branch on `schemaVersion` and `code`, not prose output.
Large-model reviews can inspect the full schema body through `schema show`;
small local models can use the policy receipt as a compact map of what is
stable.
