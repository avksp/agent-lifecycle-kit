# CI test timings

The `ci` workflow retains a `test-timings-<os>-py<version>` artifact for
14 days for every attempted stdlib test step, including failed steps. The
OS/Python matrix, direct security suite and subsequent validators are unchanged.
This is CI instrumentation; it does not change the ALK application version.

To reproduce the instrumented canonical discovery locally:

```sh
uv run --frozen --group quality python tools/ci/run_unittest.py \
  --start tests --top . --out work/ci/local-test-timings.json
```

Use a new output path for each invocation. An existing report, report write
failure, discovery/import error, incomplete run or unsuccessful unittest result
returns nonzero. A RUNNING or FAIL report is diagnostic evidence, never a pass.

The runner uses `TestLoader.discover` and executes the original nested suite
sequentially. It preserves order, duplicate IDs, fixtures, failures, skips,
expected failures and unexpected successes. Per-case monotonic duration includes
setup, the method, teardown and cleanup. Module/class fixtures and discovery
are included in `wallSeconds` and `unassignedSeconds`, not assigned to individual
methods. `suiteSeconds` excludes discovery. Fixture skips explicitly explain
cases that were discovered but never started; fixture errors remain failures.
Subtest events refer to their parent case occurrence. No missing timing is zero.
Abrupt process termination may leave only an incomplete RUNNING report.

Reports include the discovery inventory, started cases, result events, aggregate
outcomes, Python/platform and available GitHub execution identity. The regular
unittest textual diagnostics are retained. No model calls or secrets are added.

Windows jobs use `tools/ci/run_parallel_unittest.py`; Linux and macOS keep the
sequential runner above. The Windows coordinator discovers the full original
suite, then qualifies exactly one whole root subtree containing
`tests.workflow.test_limited_usage`. That subtree and the remaining original
subtrees run in two processes within the same matrix job. Nested suites,
module/class fixtures, discovery order within each group and duplicate IDs are
retained. A partition that would merge a module-fixture boundary is refused.
An unqualified partition runs the already discovered complete suite once,
sequentially, before any worker starts; the report records `mode: serial`.

Workers use separate temporary Git clones of the exact committed HEAD with
`--no-hardlinks`, separate scratch directories and a restored versioned fixture
in each clone. Tracked or nonignored untracked source changes refuse launch.
Each worker verifies detached HEAD, the complete ordered inventory and its
assigned ordered subtree roster before running tests. The parent checks both
reports and the exact complete test-ID multiset. Worker failures do not skip the
other group's ordinary execution. Missing, stale, partial, inconsistent,
interrupted or failed reports cannot pass; no test rerun or serial fallback
occurs after workers start. Existing bounded process-tree ownership and cleanup
are used; ownership or cleanup failure remains a failure. Clones isolate test
repository state, not the entire OS or external services.

Windows artifacts contain the parent report, `test-timings/<worker>/roster.json`,
per-worker reports and complete stdout/stderr logs, including on failure.
`alk-ci-test-timings.parallel.v1` separates `parallelWallSeconds`,
`summedWorkerWallSeconds`, `summedCaseSeconds`, setup, worker-window and
verification/cleanup time. Overlapping case work is never subtracted from
parallel wall time as if it were sequential overhead. Individual worker reports
retain the original sequential schema; `--worker-roster` is internal worker
selection and does not itself certify a complete suite. Default sequential
runner behavior is unchanged. Wall fields exclude final JSON serialization;
provider test-step duration includes all command startup, cloning, discovery,
log and report writes.

The manual-only `ci-timing-control` workflow runs both full modes in one
Windows/Python3.11 job at the same checkout SHA. Its fixed order is parallel
first, then sequential: any cache warming therefore benefits the sequential
control, rather than favoring the proposed optimization. Both steps share one
runner/image/interpreter; compare their provider step times. Cross-job image
versions can differ even at the same SHA and runner label, so that comparison
cannot certify the gate. Keep the recorded incomparable sample. Manual dispatch
is available only for a separately authorized comparison. Ordinary pull requests
do not automatically repeat this expensive measurement.
The initial promotion gate requires all normal OS/Python3.11–3.15 checks plus the successful
control, identical full inventory/outcomes/skips, matching available environment
identity and at least **15% lower provider test-step wall time**. Retain the
original and failed samples. Do not rerun a pair merely to obtain a favorable
timing. One pair is an observed result, not a median, p95 or future guarantee;
queue time, job wall and total runner minutes are separate measures. Comparison
evidence belongs to the [infrastructure PR](https://github.com/avksp/agent-lifecycle-kit/pull/189).
That PR recorded 2144 seconds parallel versus 2712 seconds sequential: a 20.94%
reduction for one same-job Windows/Python3.11 pair with identical 3721-case
inventories and outcomes. This is a historical observation, not a new measurement
for later source revisions.

The temporary Git repositories used by the parallel-runner regression tests
disable automatic maintenance and garbage collection per Git invocation. Ambient
Git defaults cannot launch detached housekeeping from those fixture commands;
real clone, safety and strict cleanup assertions remain. This does not change
the production runners or establish the writer/cause of the separately preserved
CI temporary-directory cleanup failure, which remains unproven.

No fixture cache or
application/dependency version change is included. Roll back the Windows runner
selection to `run_unittest.py` if the promotion gate fails; retain its evidence.

The result hooks follow the [Python unittest runner contract](https://docs.python.org/3.11/library/unittest.html#unittest.TextTestRunner).
Artifact behavior follows [actions/upload-artifact](https://github.com/actions/upload-artifact).
