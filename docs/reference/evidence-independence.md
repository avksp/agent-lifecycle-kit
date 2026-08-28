# Evidence independence

[Русская версия](../ru/reference/evidence-independence.md)

ALK distinguishes ordinary evidence from statistical evidence. Ordinary task
receipts keep their existing path. A statistical or error-rate claim must also
declare where every sample came from, how it was derived and why it is
independent from the implementation under review.

## Contracts

The general independence path uses:

- `agent-independence-requirement.v1`;
- `agent-independent-evidence.v1`;
- `agent-independent-evidence-validation.v1`.

The statistical path uses:

- `agent-statistical-evidence-requirement.v1`;
- `agent-statistical-evidence-set.v1`;
- `agent-statistical-evidence-validation.v1`.

The `statistical-check` method extends the existing `deterministic-check` and
`human-review` methods. It does not make statistical evidence mandatory for an
ordinary non-statistical acceptance criterion.

## Required provenance

Each statistical sample declares a stable sample identity, source class,
derivation identity, source revision, source-lineage digest and independence
statement. Source classes are `IMPLEMENTATION`, `INDEPENDENT_HOLDOUT` and
`EXTERNAL_OBSERVATION`.

Effective count includes only unique samples on the required current lineage.
Duplicate identities, stale revisions, stale lineage and an undisclosed shared
producer between implementation and holdout evidence fail closed. Raw payloads
are not copied into the validation result; the bounded projection records only
the declared provenance fields and digests.

## Adequacy

The supported zero-error bound is the exact 95% rule of three. The minimum
effective independent sample count is derived from the declared error
threshold:

- a 2% claim requires at least 150 samples; 149 fails;
- a 1% claim requires at least 300 samples; 299 fails.

The validator uses exact decimal arithmetic and a bounded maximum of 10,000
samples. A larger collection, unsupported method or malformed requirement is a
stable validation failure rather than a reason to skip the check.

## Authority boundary

Statistical evidence can satisfy only a criterion that explicitly references
its evidence ID. It cannot approve a plan, accept a task, close a finding or
replace independent review. Missing provenance is `UNAVAILABLE` or blocking;
it is never inferred from reviewer agreement or a successful process exit.

See [Review efficiency](review-efficiency.md), [Review Mesh](review-mesh.md)
and [risk-bound independent verification](risk-bound-independent-verification.md).
