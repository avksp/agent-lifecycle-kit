# Research evidence

[Русская версия](../ru/reference/research-evidence.md)

Research evidence is a bounded input package for technical investigation,
architecture analysis and plan preparation. It connects source references,
claims, citations and provenance before the material is used by a lifecycle
workflow.

The package is advisory context. The reviewed specification, frozen plan,
acceptance criteria and implementation evidence remain the source of truth for
ALK decisions.

## Typical workflow

1. A host adapter or operator prepares `research-evidence.json` from selected
   sources. Each claim points to its supporting source and citation.
2. The operator supplies only the package and any explicit UTF-8 snapshots that
   are needed to verify quoted ranges.
3. ALK validates bindings, digests, provenance, lifecycle status, size limits
   and security boundaries without network access, model calls or host-process
   launches.
4. ALK writes a validation receipt and a bounded summary. The summary can be
   attached to a draft specification or plan for review.

## Commands

Validate a package and verify a citation against a local source snapshot:

```bash
agent-lifecycle research validate \
  --package work/research/research-evidence.json \
  --snapshot source-1=work/research/snapshots/source-1.txt \
  --out work/research/validation.json
```

Create a compact summary from the package and its validation receipt:

```bash
agent-lifecycle research summary \
  --package work/research/research-evidence.json \
  --validation work/research/validation.json \
  --out work/research/summary.json
```

The output path is write-once. Use a new path for a new validation attempt so
that an earlier receipt cannot be silently replaced.

## Package contents

| Record | Purpose |
| --- | --- |
| Source | Identifies the origin, kind, locator, source digest and optional snapshot digest. |
| Claim | States one bounded conclusion and names its supporting sources and citations. |
| Citation | Binds a claim to a source and, when a snapshot is supplied, to a quoted UTF-8 range and digest. |
| Provenance edge | Describes a seed, derived, duplicate or suggested relationship between sources. |
| Resource caps | Limits package size and record counts before processing. |
| Redaction | Declares that raw source content and sensitive values are not stored in the portable package. |

The seven public schemas are:

- `agent-research-source.v1`
- `agent-research-claim.v1`
- `agent-research-citation.v1`
- `agent-research-provenance-edge.v1`
- `agent-research-evidence-package.v1`
- `agent-research-evidence-validation.v1`
- `agent-research-evidence-summary.v1`

## Reading the result

`research validate` returns a validation receipt:

- `PASS` means the package is structurally valid, bindings and supplied
  snapshots agree, provenance has no blocking cycle and security checks pass.
- `FAIL` contains bounded `blockers` with stable codes. Do not use the package
  as accepted research input until the blockers are resolved or the package is
  explicitly replaced.
- A citation with `UNAVAILABLE` means its source snapshot was not supplied.
  The package can remain structurally valid, but the summary reports an
  evidence gap and does not count that claim as supported.
- A citation with `MISMATCH` records a reported disagreement and does not turn
  into a verified quote.

The summary lists `supportedClaims`, `evidenceGaps`, duplicate groups and
lifecycle counts. It contains digests and identifiers, not source bodies,
transcripts or prompts.

## Provenance and independence

Copies and articles derived from one source are represented as
`duplicate-of` or `derived-from`. They are not counted as independent sources.
Cycles in provenance are blocking because they make the origin ambiguous.
Disconnected sources are reported so a reviewer can distinguish independent
material from a collection of unrelated references.

## Security boundary

Research packages are untrusted input. Validation rejects raw source fields,
provider or model fields, prompt-authority markers, secret-like content and
private absolute paths. Locators are metadata only: ALK does not fetch URLs,
open arbitrary file references or execute instructions found in source text.

Research evidence cannot change a plan, approve a task, satisfy an audit gate
or claim production readiness. A model or host may use the summary to prepare
draft requirements, but the normal specification review and plan freeze are
still required.

## Limits

The default package and snapshot limit is 32 MiB. The package is bounded to
128 sources, 256 claims, 256 citations and 512 provenance edges. Use several
reviewed packages when an investigation is larger; do not bypass the limits by
embedding raw documents in metadata.

See [public contracts](public-contracts.md) for the complete schema policy and
[the research workflow guide](../guides/research-workflow.md) for examples.
