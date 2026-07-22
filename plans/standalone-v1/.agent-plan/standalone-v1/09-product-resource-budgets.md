# Product Resource Budget Profile

Profile id: `agent-lifecycle-budget-profile.v1`

The machine-readable authority is
`agent-lifecycle-budget-profile.v1.json`. This document explains the same
values; any mismatch is a freeze blocker.

This profile governs the shipped lifecycle. Manifest orchestration values
govern only this implementation run and may be stricter; they never replace
the product profile.

## Normalized Measurements

- Billable tokens come from host attestation. Raw provider counters remain in
  the receipt and are never reinterpreted destructively.
- Context bytes are the exact rendered prompt envelope before transport.
- A logical semantic call is one budgeted usage event. It may be a live
  provider invocation or a deterministic replayed event. A live model
  invocation is an actual provider call. Deterministic validators consume zero
  logical calls and zero model tokens; replay benchmarks exercise logical-call
  ceilings while making zero live model invocations.
- One semantic iteration is a controller-authorized task-attempt slot and may
  contain zero or one logical semantic call. Per-task logical-call usage is the
  sum across every stage and attempt attributed to that task. Per-run usage
  also includes lifecycle stages outside tasks. Review, remediation, fallback,
  retries and cache reuse never reset either counter.
- Tool calls, validation runs and wall time are cumulative by stage, task and
  run. Cache read/write counters are recorded separately.
- Missing or unverifiable usage is a hard failure, not zero usage.

## Hard Run Ceilings

| Metric | S0 | S1 | S2 |
| --- | ---: | ---: | ---: |
| Billable tokens per run | 100000 | 300000 | 1000000 |
| Context bytes per semantic call | 32768 | 65536 | 131072 |
| Cumulative context bytes per run | 393216 | 2097152 | 25165824 |
| Semantic iterations per attempt | 2 | 3 | 4 |
| Logical semantic calls per task | 4 | 6 | 8 |
| Logical semantic calls per run | 12 | 32 | 192 |
| Tool calls per iteration | 12 | 16 | 20 |
| Tool calls per task | 30 | 45 | 60 |
| Tool calls per run | 80 | 250 | 600 |
| Validation runs per task | 2 | 3 | 3 |
| Task attempts | 2 | 2 | 2 |
| Parallel executable tasks | 1 | 1 | 4 |
| Evidence bytes per artifact | 8388608 | 16777216 | 16777216 |
| Evidence bytes per task | 33554432 | 67108864 | 67108864 |
| Evidence bytes per run | 134217728 | 268435456 | 536870912 |
| Task wall seconds | 1800 | 3600 | 7200 |
| Run wall seconds | 3600 | 14400 | 86400 |

## Hard Stage Token Ceilings

Values are per stage occurrence; task-scoped stages are per task attempt.

| Stage | S0 | S1 | S2 |
| --- | ---: | ---: | ---: |
| Clarification | 4000 | 8000 | 16000 |
| Specification authoring | 0 | 12000 | 40000 |
| Specification review | 0 | 8000 | 30000 |
| Plan authoring | 8000 | 20000 | 60000 |
| Plan review | 6000 | 16000 | 45000 |
| Implementation per task | 32000 | 64000 | 120000 |
| Task review per task | 8000 | 16000 | 30000 |
| Remediation per task | 16000 | 32000 | 60000 |
| Final audit | 12000 | 24000 | 60000 |

An adapter may select one model for multiple stages or different models. The
same ceilings apply after fallback; fallback never resets a counter.

## Frozen Benchmark Corpus

- `S0-MECHANICAL-01`: one bounded low-risk edit and deterministic validation.
- `S1-STANDARD-01`: one-owner implementation with embedded specification.
- `S2-MULTI-01`: four-owner parallel DAG with integration and final audit.
- `S2-SECURITY-01`: neutrality, permission and forged-receipt negatives.
- `S2-RECOVERY-01`: interruption, WAL recovery, remediation and refreeze.

Release evidence runs at least twenty cold-cache and twenty warm-cache runs for
every scenario: two hundred runs in total. These are deterministic synthetic
host replays with schema-valid usage attestations, scenario-specific replayed
semantic calls and zero live model invocations. This exercises semantic-call,
stage and run ceilings without consuming two hundred live-model calls, and one
benchmark command plus receipt covers the cohort without consuming two hundred
orchestration tool calls. The gate proves prompt/context accounting, caching,
budgets, state transitions and audit quality.

A separate required live calibration uses the external
`agent-lifecycle-benchmark-authority.v1` profile: one cold and one warm run for
the S0 mechanical, S1 standard and S2 multi-owner scenarios, at most 120000
billable tokens and 7200 wall seconds in total. It must preserve acceptance and
audit quality and provide host-attested usage. It validates real transport and
usage behavior but cannot replace or weaken the deterministic two-hundred-run
gate. Pre-merge smoke may use five deterministic runs but cannot promote a
release.

## Measurement Aggregation

The per-call context ceiling is checked on every rendered semantic envelope.
The hard cumulative-run context ceiling is checked after each logical call and
before the next launch. It equals the exact sum of those pre-transport envelope
byte counts; it is independent from, and cannot be weakened by, the lower p95
release SLO. Logical-call task and run ceilings are checked before dispatch and
again when usage is reconciled. Percentiles are calculated over complete
scenario runs, never over individual calls, tasks or model-provider counters.
Failed runs remain in the cohort and fail the quality gate; they are not
discarded as outliers.

## Absolute Release Targets And Regression Rule

| Metric | S0 p95 | S1 p95 | S2 p95 |
| --- | ---: | ---: | ---: |
| Billable tokens per run | 70000 | 220000 | 800000 |
| Cumulative context bytes per run | 196608 | 1048576 | 16777216 |
| Tool calls per run | 60 | 180 | 500 |
| Wall seconds per run | 2700 | 10800 | 72000 |

These p95 values are hard release SLOs, not advisory diagnostics. Additional
telemetry may define advisory optimization targets, but it cannot weaken these
tables or any hard ceiling.

For the first production release, no relative baseline exists. The candidate
must pass all semantic acceptance and audit verdicts, every hard ceiling and
every absolute p95 SLO. A successful independently audited release then emits a
signed, content-addressed baseline containing the corpus digest, profile id,
per-run measurements and p50/p95 aggregates. From the second release onward,
the immediately prior accepted baseline is mandatory and relative regression
must be at most 5 percent at p50 and 10 percent at p95 for billable tokens,
cumulative context bytes per run, tool calls and wall time.

Missing prior baseline on a non-first release, a baseline created by the
candidate under test, corpus mismatch or signature failure is a hard failure.
An intentional baseline reset requires a new profile version, independent
review and release approval; it cannot be hidden inside a fixture or adapter
update.
