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
