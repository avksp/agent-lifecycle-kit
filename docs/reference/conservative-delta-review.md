# Conservative plan review

Release 2.22 can reuse complete independent plan-review coverage while asking
each required reviewer to assess the changes and confirm current applicability.
It selects review scope; it does not launch a model or accept a plan.

## Select a review packet

```bash
agent-lifecycle plan review-packet \
  --repository-root . \
  --manifest tasks/my-plan-r2/plan.manifest.json \
  --baseline tasks/my-plan-r1/review.json
```

The manifest path is canonical and relative to the repository root. All
normative files, historical reports, authority and closure evidence must exist
with their original bytes. The complete runtime inventory is checked against
the exact Git source and the current checkout. Unknown or changed runtime
files prevent reuse. Keep advisory output in an already ignored work directory
so it cannot become an unexplained runtime input to a subsequent selection.

Optional `--out work/example.review-packet.json` and
`--subject-out work/example.review-subject.json` create advisory files only.
The suffixes are required; protected plan directories, existing destinations,
reserved control paths and symlink traversal are rejected. No output is written
when selection returns `FULL_REQUIRED`. The subject contains the manifest and
the complete file/runtime hash maps needed by a real reviewer; neither artifact
is a review, lock, execution authorization or workflow transition.

| Mode | Meaning | Next action |
| --- | --- | --- |
| `FULL` | No baseline supplied; complete review is the default. | Use existing admission and independent full plan review. |
| `DELTA_ELIGIBLE` | A complete baseline and explicit change closure are available. | Obtain current independent delta/applicability judgments for every required seat. |
| `FULL_REQUIRED` | These inputs cannot prove safe reuse. | Repair missing evidence and select again, or admit a full review of the current plan package. |

`FULL_REQUIRED` never schedules a model call. It does not order a new audit of
the entire project. A missing reference can be repaired without repeating valid
reviews. Changed source, unknown impact or incomplete historical coverage may
require a genuinely new full plan review. A missing finding closure or current
applicability conclusion blocks acceptance; supply the missing independent
evidence when the existing coverage remains applicable.

## Coverage and acceptance

Selection derives requirement, acceptance, evidence, task, ownership, security
and final-gate dependencies from both manifests. Changed and removed edges
retain their old dependants. Unchanged digests alone grant no approval.

The reusable baseline is a bound `agent-plan-review.v2` full report, or a
verified `agent-plan-composite-review.v1` conclusion with its complete report
set. A complete `CHANGES_REQUIRED` baseline can provide coverage, but its
blocking findings must be independently closed before present acceptance.
`BLOCKED`, partial and unavailable verdicts cannot establish a full baseline.
Legacy full reviews retain the existing full-review route.

The governing `extensions.reviewPolicy` declares required seats, allowed
reviewers and any surface diversity. Each seat has one full root and a bounded
linear series of change reviews. Replacements must be authorized and explicitly
adopt the root evidence. Repeated delivery of one report creates no new voice.
Required dissent, open Medium or higher findings and incomplete seats cannot
be hidden or pooled. The coordinator supplies no independent reviewer seat.

Every final seat explicitly confirms the exact candidate, unchanged baseline
applicability, complete coverage, all reviewed changes and resolved blockers.
Composite and delta reports retain `fullReview: false`; a complete coverage
conclusion does not relabel a partial report as full.

Use `plan freeze-prepare` to produce the exact candidate before its review.
`plan lock-create` revalidates the bound evidence and current source before
creating the canonical lock. An explicit review policy and valid composite
produce `agent-plan-lock.v3`. The manifest's existing inventory declaration
remains `agent-plan-lock.v2`; it does not authorize a scope downgrade. Legacy
independent full-review locks remain v2. Older readers reject the new v3 scope.
Subsequent lifecycle verification checks the pinned historical source, allowing
authorized task implementation to change current source without invalidating
the already created lock.

## Limits and measurements

Each seat is limited to 16 reports, eight dependency edges in the longest chain
and 8 MiB of raw report bytes. Stricter governing limits win. Impact graphs have
at most 4096 nodes and 16384 edges; packets are capped at 98304 canonical UTF-8
bytes (`--max-bytes` can lower this to at least 1024). Overflow refuses reuse;
caps never grow automatically. Existing execution, security and quality gates
continue to apply. Reuse does not renew authorization or reset spent resources.

`tools/release/validate_delta_review_equivalence.py` executes labelled synthetic
full/delta pairs and negative cases. It checks fixed-workload findings, readiness,
blocking gates, coverage, lineage, dissent, redelivery and limits. Observed
packet bytes and graph counts are deterministic measurements. The `FULL`
selection header is not a full model prompt, so its size is not evidence of
model-token savings.

Existing `metrics audit-efficiency` inputs can include `planReviewPairs` with
unique case IDs and the two observed findings/readiness/blocking-gate views,
packet bytes and selected graph counts. The report adds a validated
`planReviewComparison`; a mismatch fails the report. This declared deterministic
view is not independent model approval. Candidate model tokens, token reduction
and cost remain `UNAVAILABLE` without genuinely comparable real generations.
Historical source-native usage remains historical and is never charged again.
