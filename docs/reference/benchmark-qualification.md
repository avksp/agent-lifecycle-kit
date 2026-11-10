# Validate execution setups with reference tasks

[Русская версия](../ru/reference/benchmark-qualification.md)

This guide answers a narrow question: whether two externally produced ALK runs
are comparable on quality and resource evidence. An execution setup is the
neutral combination of an adapter, model class, environment and scorer. The
external adapter, model or harness performs the run. ALK reads the resulting
execution records, checks their lineage and produces a bounded report without
starting a process. The technical schema name keeps `receipt` for compatibility.

## Separate dimensions

Every run keeps these dimensions separate:

- task fixture, family, tier and explicit shape;
- neutral adapter and execution-setup class;
- environment digest;
- scorer digest;
- source execution-record digest.

Provider names, model names, commands, credentials and absolute local paths do
not belong in the portable execution record. A setup class such as `standard` or
`local-code` is a neutral classification, not a provider identity.

## Select a reproducible sample

```bash
agent-lifecycle benchmark sample \
  --suite benchmarks/reference-tasks/manifest.json \
  --seed project-baseline \
  --max-tasks 24 \
  --max-strata 16 \
  --out work/benchmark/sample.json
```

The selection is deterministic for the same suite, seed and bounds. Strata use
the manifest fields `family`, `tier` and `shape`; the result records selected
and omitted task identifiers. The bundled suite declares five bounded shapes:
`planning`, `review`, `investigation`, `implementation` and `evidence`.

## Validate an external execution record

The runner creates an `agent-benchmark-run-receipt.v1` file. Its setup,
environment, scorer and source objects contain digest-bound neutral metadata.
ALK validates the execution record without invoking the declared runner:

```bash
agent-lifecycle benchmark receipt-check \
  --suite benchmarks/reference-tasks/manifest.json \
  --receipt work/benchmark/run-01.json \
  --out work/benchmark/run-01-validation.json
```

The validation result is `agent-benchmark-run-receipt-validation.v1`. A stale
task digest, missing axis digest, mixed portable data or a changed execution
record digest is rejected.

## Validate an execution setup

Pass one execution record per `--receipt` option. Use the same sample for every setup
being compared:

```bash
agent-lifecycle benchmark qualify \
  --suite benchmarks/reference-tasks/manifest.json \
  --sample work/benchmark/sample.json \
  --receipt work/benchmark/baseline-01.json \
  --receipt work/benchmark/baseline-02.json \
  --out work/benchmark/baseline-qualification.json
```

An execution setup receives the technical status `QUALIFIED` only when it has all
of the following:

- at least five distinct tasks;
- at least two completed runs for every task;
- at least five distinct `family/tier/shape` strata;
- at least two completed runs for every stratum;
- criteria totals and passed criteria for every run;
- an explicit false-acceptance result and no quality measurement gap.

Otherwise the report returns `NO_RECOMMENDATION`. Quality and false acceptance
are checked before token, time, retry or resource comparisons.

## Compare two execution setups

```bash
agent-lifecycle benchmark compare-routes \
  --suite benchmarks/reference-tasks/manifest.json \
  --sample work/benchmark/sample.json \
  --baseline work/benchmark/baseline-01.json \
  --baseline work/benchmark/baseline-02.json \
  --candidate work/benchmark/candidate-01.json \
  --candidate work/benchmark/candidate-02.json \
  --out work/benchmark/route-comparison.json
```

The comparison keeps setup, environment and scorer changes visible. Different
task pools, environments, scorers or usage-attestation classes produce an
`INCOMPARABLE` or `NO_RECOMMENDATION` result instead of a misleading winner.
The result is advisory and cannot switch an adapter, model or frozen plan.

## Hosted, small and local models

The same workflow accepts execution records from a hosted model, a small-context model
or a local model. The host-owned adapter supplies its own neutral setup class,
environment digest and usage confidence. ALK does not infer missing token data,
does not combine estimated and attested totals, and does not treat missing
measurements as no usage. It does not turn a benchmark report into a production
support claim.

## Qualified evidence ranking

```bash
agent-lifecycle benchmark rank-qualified --request local-ranking.json --out new-report.json
```

The pure API is
`agent_lifecycle.model_routing.qualified_selection.rank_qualified_routes(request, *, now=None)`.
Only library tests may inject `now`; the CLI uses current UTC. Manual requests
contain `schemaVersion=agent-qualified-route-ranking-request.v1` and optionally
`enabled=false`. An enabled request additionally requires all of:

- `modelRequest` and `routingProfile`, using the existing model routing contracts;
- `hostIdentityDigest`, `productSourceDigest`, `environmentDigest`, `scorerDigest`;
- `metric`: `tokens` or `elapsedMilliseconds`; `maxAgeSeconds`: integer 1..604800;
- `trustedReceiptDigests`: at most 192 distinct lowercase SHA256 values;
- `candidates`: at most three objects containing exactly `id`, `hostProfile`,
  `modelClass`, `hostBindingDigest`, and `receipts` (at most 64 each).

Candidate IDs are portable opaque identifiers, 1..64 characters. IDs and binding
digests are distinct, every host profile names the same host, and the resolver's
selected class/binding must match the candidate. All digests use lowercase hex.
Inputs are limited to 1 MiB, depth 16 and 12000 JSON value nodes. Unknown keys,
duplicate JSON keys, invalid numeric types, nonfinite values and links are refused.
Reports are at most 64 KiB. No referenced evidence path is opened.

`trustedReceiptDigests` is the caller's allowlist of full receipts previously
independently accepted outside this consumer. Hash equality establishes integrity
against that list, not authentication, financial attestation, supported hosts or
complete collection. ALK cannot discover missing calls or prove that a producer
observed every contribution. No signing or trust registry is introduced.

Every receipt must pass the existing validator and fresh qualification using the
unchanged minima: five distinct tasks, two completed runs/task, five strata and
two runs/stratum. Every quality criterion passes, false acceptance is false,
measurement gaps are empty and usage confidence is `ATTESTED`. Receipt IDs and
full digests are globally unique. Replayed rows cannot satisfy the minima.

Each receipt's `measurements.acceptedTaskTotal` contains exactly `scope`,
`accepted`, `complete`, `observedAt`, `hostIdentityDigest`,
`productSourceDigest`, `contributions`. Scope is `ACCEPTED_TASK_TOTAL`; both
booleans are true. `observedAt` is UTC RFC3339, not future, with age no greater
than `maxAgeSeconds` (the exact boundary is accepted). Host/source digests match
the request, as do the receipt's environment and scorer digests.

Each contribution contains exactly `id`, `role`, `tokens`,
`elapsedMilliseconds`, `evidenceDigest`. IDs are unique within the task. All six
roles must appear: coordinator, worker, review, audit, retry, correction. A zero
share is explicit and provenance-bound. Missing roles, unknown totals or absent
64-hex evidence digests cannot be assumed zero. Counters are integers in
0..2**53-1; booleans are invalid. Both contribution sums equal the receipt's
outer totals. Token shares include input/output and nested cache/reasoning once;
shares do not overlap. Elapsed shares represent accepted-task intervals, never
summed overlapping reviewer wall time. Producer normalization remains external.

Every candidate has the identical multiset of task ID/version/digest,
family/tier/shape and run counts. Product source, host, environment and scorer
match; individual source execution digests may differ. Pairwise existing route
comparisons must pass with attested usage before resources are ranked. Any gap
refuses the whole allowlist. Ranking uses ascending integer sums of the requested
metric and input priority for ties; it makes no extrapolation.

The report schema is `agent-qualified-route-ranking.v1`. It records status,
bounded reason codes, selected candidate ID or null, ranking, metric, request,
qualification, comparison and report digests. Refusal has an empty ranking.
Private host model names are omitted. All reports retain `advisoryOnly=true`,
`automaticRouteAdoptionEligible=false`, `productionPromotionClaimed=false`,
`modelCallsStarted=false`, `hostLaunchStarted=false`, `profileMutation=false`,
`liveEconomicQualification=UNQUALIFIED`, and `savingsClaimed=false`. Positive
fixtures are `UNIT_ONLY`; live economic qualification remains deferred.
