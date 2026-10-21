# CI test timings

The `ci` workflow retains a `test-timings-<os>-py<version>` JSON artifact for
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

Next, use actual Windows measurements to choose balanced execution groups,
prove that their union preserves the complete test-ID multiset, and verify
failure propagation. Reuse only measured immutable fixture preparation after
separate review. This change does not yet implement parallel groups or establish
a speedup. Compare wall time, queue time and total runner minutes separately.

The result hooks follow the [Python unittest runner contract](https://docs.python.org/3.11/library/unittest.html#unittest.TextTestRunner).
Artifact behavior follows [actions/upload-artifact](https://github.com/actions/upload-artifact).
