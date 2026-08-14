# Run the reference task suite

Use the bundled suite when you need a repeatable local comparison of an ALK
process change. No model account or external CLI is required.

For multi-run comparison of adapter setups and environments, continue with
[execution-setup validation](../reference/benchmark-qualification.md). This guide
covers one-task oracle evaluation; the validation page adds stratified sampling
and minimum evidence gates.

## 1. Start from an example

```bash
mkdir -p work/benchmark
cp tests/benchmarks/fixtures/accepted-pass.json work/benchmark/submission.json
```

The example represents a passing planning result. Replace its `evidence`
objects with receipts from your own controlled run while keeping `taskId` and
`taskVersion` aligned with the suite manifest.

## 2. Evaluate

```bash
agent-lifecycle benchmark evaluate \
  --suite benchmarks/reference-tasks/manifest.json \
  --artifact work/benchmark/submission.json \
  --out work/benchmark/evaluation.json
```

Read these fields first:

- `status`: whether the accepted result passed its deterministic oracle;
- `summary.falseAcceptanceCount`: accepted result that the oracle rejected;
- `measurements.tokens.byConfidence`: attested and estimated token buckets;
- `measurements.measurementGaps`: data that was not supplied.

## 3. Exercise the negative case

```bash
agent-lifecycle benchmark evaluate \
  --suite benchmarks/reference-tasks/manifest.json \
  --artifact tests/benchmarks/fixtures/accepted-false.json \
  --out work/benchmark/false-acceptance.json

python -c 'import json; value=json.load(open("work/benchmark/false-acceptance.json")); assert value["status"] == "FAIL" and value["summary"]["falseAcceptanceCount"] == 1'
```

The evaluation command returns normally because it produced a valid negative
receipt. The second command enforces the benchmark outcome in automation.

## Advanced use

Advanced users can create a separate submission for each task in
`benchmarks/reference-tasks/manifest.json`, retain the resulting receipts, and
compare quality, elapsed time, retries, and confidence-labeled tokens across
changes. Do not compare an `ESTIMATED` value with an `ATTESTED` value as if they
had the same provenance.

See [Reference task evaluation](../reference/reference-task-evaluation.md) for
the input contract, oracle predicates, and security boundary.
