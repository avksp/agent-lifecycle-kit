# Risk-bound independent verification

Release 2.1 adds a criterion-scoped evidence contract for cases where a high-risk
claim needs corroboration from a genuinely separate producer, implementation
lineage or source revision. It is optional and inactive by default. Ordinary
ALK criteria continue to use their existing deterministic checks and review
evidence.

## When to use it

Declare independent verification only when the frozen criterion is important
enough that a check produced by the primary implementation path is not enough.
Typical examples are:

- a security or architecture claim checked by a separate implementation of the
  check;
- a release-scope claim reviewed against a source revision not produced by the
  implementation worker;
- a deterministic boundary test whose producer and implementation must be
  independently attributable.

Do not add it to ordinary criteria just to increase the number of receipts.
The requirement is part of the criterion before execution and cannot be added
after a result merely to accept or reject that result.

## Declare the requirement

A plan criterion may contain an `independence` object and route its evidence
through `independentEvidenceIds`:

```json
{
  "id": "AC-SECURITY-BOUNDARY",
  "independence": {
    "schemaVersion": "agent-independence-requirement.v1",
    "required": true,
    "requiredDimensions": ["producer", "implementation", "source"],
    "allowedMethods": ["deterministic-check", "human-review"],
    "prohibitedProducerClasses": ["implementation-worker"],
    "sourcePolicy": "exact-revision",
    "productionPromotionClaimed": false,
    "requirementDigest": "<digest of the preceding fields>"
  },
  "independentEvidenceIds": ["EV-SECURITY-BOUNDARY"]
}
```

Use `build_independence_requirement()` to create the digest-bound object. Plan
completeness requires an evidence route for every criterion whose requirement
is marked `required: true`.

The supported dimensions are producer, implementation and source. The source
policy is explicit: an exact revision requires the expected revision and
lineage at the gate; current-lineage and any-current are available for
criteria whose plan deliberately allows those scopes.

## Evidence record

An `agent-independent-evidence.v1` record contains only bounded facts:

- criterion and requirement digests;
- source revision and source-lineage digest;
- method (`deterministic-check` or `human-review`);
- producer class and an identity hash;
- implementation digest;
- status, findings and an unavailable reason when applicable.

`rawReasoningStored`, `rawTranscriptStored` and
`productionPromotionClaimed` are always false. Hidden reasoning, full review
transcripts, credentials and provider names are not portable evidence.

The evidence validator checks the requirement digest, allowed method,
prohibited producer classes, expected source lineage and primary implementation
digest. Replaying a valid record against a different revision or sharing the
primary producer/implementation yields a failed validation.

## Review and gating

Review Mesh assignment packets carry the frozen requirement. A required
criterion must provide a `PASS` evidence record before its result can pass
through Review Mesh or quorum validation. `UNAVAILABLE`, stale and malformed
evidence fail closed for that criterion.

An optional requirement remains advisory: missing evidence does not change
unrelated task or run authority. Review Mesh still does not start a model,
host CLI or network service; the operator or adapter-owned wrapper produces
the bounded record and ALK validates it.

## Security and authority boundaries

Independent evidence is corroboration, not a second workflow authority. It
cannot change ownership, authorize a command, bypass a security gate, promote
an adapter or replace the frozen plan. The existing workflow state, plan and
acceptance contracts remain authoritative.

The feature also preserves the ordinary ALK guarantees: no runtime
dependency, no provider-specific execution in the core, no cache of trust
decisions and no weakening of freshness, redaction, signature or resource
checks.

See [Review Mesh](review-mesh.md), [public contracts](public-contracts.md) and
the [Russian reference](../ru/reference/risk-bound-independent-verification.md).
