# Research workflow

[Русская версия](../ru/guides/research-workflow.md)

Use this workflow when a task needs an architecture study, comparison of
external material, investigation before planning or a review of several
independent sources.

## When to use it

Use a research package when the result must be traceable later or when several
people or models contribute findings. For a short private note, a normal task
file is enough. Research evidence becomes useful when a claim needs a source,
a quote and a clear indication of whether two sources are actually independent.

## Step 1: collect material

Keep the source documents in the operator's working area. Prepare one UTF-8
snapshot per source when exact quote verification is needed:

```text
work/research/
  research-evidence.json
  snapshots/
    source-1.txt
    source-2.txt
```

The portable package stores locators, digests and redaction metadata. It does
not store full documents, prompts, secrets or provider and model names. A host
adapter or an operator-side tool creates the package according to
`agent-research-evidence-package.v1`; ALK validates it but does not fetch the
referenced sites or build a conclusion from a URL.

## Step 2: validate the package

```bash
agent-lifecycle research validate \
  --package work/research/research-evidence.json \
  --snapshot source-1=work/research/snapshots/source-1.txt \
  --snapshot source-2=work/research/snapshots/source-2.txt \
  --out work/research/validation.json
```

Add a `--snapshot SOURCE_ID=PATH` argument only for a source whose quoted range
must be checked locally. A missing snapshot is reported as `UNAVAILABLE` and
creates an evidence gap; it is not silently treated as a verified quote.

## Step 3: read the summary

```bash
agent-lifecycle research summary \
  --package work/research/research-evidence.json \
  --validation work/research/validation.json \
  --out work/research/summary.json
```

Check these fields first:

- `status`: whether the package passed deterministic validation;
- `supportedClaims`: claims with a matched citation and no stale or disputed
  status;
- `evidenceGaps`: claims that still need a source or a verified quote;
- `duplicateGroups`: sources that must not be counted as independent;
- `lifecycleCounts`: the distribution of draft, reviewed, accepted, stale and
  disputed records.

## Step 4: use the result in planning

Treat the summary as reviewed input for a draft specification. Convert useful
claims into explicit requirements, assumptions and acceptance checks. Record
which claims require a test, a code inspection or another domain confirmation.
Then run the normal ALK planning flow:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md --mode plan
agent-lifecycle plan check --manifest <plan-directory>/plan.manifest.json
```

Research validation does not freeze a plan and does not grant implementation
authority. A claim can inform a requirement, but the requirement becomes part
of the lifecycle only after specification review, plan acceptance and freeze.

## Multi-model and multi-source work

Different adapters or models may prepare separate source records or claims.
Keep their outputs separate until provenance and citations are recorded. Review
Mesh can then prepare reviewer packets and synthesize findings. The research
validator checks the evidence package locally; it does not contact any model
or decide which model's conclusion is correct.

## Common cases

| Case | Recommended input | Next ALK step |
| --- | --- | --- |
| Architecture study | Sources, claims, citations and dependency relationships | Draft an architecture section and plan review questions. |
| External project comparison | One source per project, with duplicate and derivative links | Prepare a bounded comparison and mark unsupported claims as gaps. |
| Incident or bug investigation | Reproduction notes, observations and source snapshots | Use the Bug Forensics profile for reproduction and regression proof. |
| Long research before implementation | Periodic reviewed packages with bounded summaries | Attach each summary to the current draft and re-review changed assumptions. |
| Independent review | Separate source records for each reviewer or adapter | Use Review Mesh for assignments, import, synthesis and optional quorum. |

See [research evidence](../reference/research-evidence.md) for the contract,
security rules and complete result semantics.
