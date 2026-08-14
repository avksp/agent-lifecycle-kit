# Process execution observability

[Русская версия](../ru/reference/process-execution-observability.md)

ALK records the resources used by each bounded external-process invocation. The
purpose is operational: show whether a run spent time in the host process,
whether it exceeded a limit, and whether its process group was cleaned up.

## What is recorded

The process layer emits `agent-process-execution-receipt.v1`. The receipt is
bound to an operation and attempt, but stores no command arguments, environment,
secrets, prompts or host output. It contains:

- monotonic elapsed time, so wall-time comparisons are not affected by a system
  clock change;
- CPU time, peak memory and process count with an explicit
  `ATTESTED`, `ESTIMATED` or `UNAVAILABLE` status;
- timeout, cancellation and exit status;
- retry count and reason; and
- process-group cleanup status and blockers.

The availability label is part of the result. A missing operating-system
counter is not presented as an exact measurement.

## Build a report

The receipt is normally produced by an ALK-managed adapter or live-host
harness. Aggregate one or more receipt files locally:

```bash
agent-lifecycle metrics execution-report \
  --receipt work/evidence/process-receipt.json \
  --out work/evidence/execution-resource-report.json
```

Repeat `--receipt` for several invocations. Add `--operation-id` when the
report must be bound to one operation. The command writes
`agent-execution-resource-report.v1` and returns a digest and validation
status. The report includes elapsed time, available resource totals, timeout
and cancellation counts, and cleanup blockers.

`PASS` means that the receipts are structurally valid and cleanup is confirmed.
`BLOCKED` means that a receipt is invalid or cleanup was not confirmed. A
blocked cleanup is not converted into success by a retry.

## Process lifetime and cleanup

On POSIX systems ALK starts the child in a new process session and cleans the
owned process group on normal completion, timeout or cancellation. On Windows
the process is placed in an owned Job Object with kill-on-close behavior when
the platform provides that capability. If ownership or cleanup cannot be
verified, the receipt records the limitation and the result is blocked where
the lifecycle requires cleanup proof.

Retries are bounded and are decided from the receipt. A cleanup failure is a
stop condition, not a reason to create another host process.

## Scope

The collector is local and bounded. It does not run a daemon, call a model,
connect to a provider or store raw host output. It complements token receipts:
host-local adapters attest exact token counts, while this contract describes
process time and operating-system resource counters.

For security rules around local host launches, see [managed adapter sessions](managed-adapter-sessions.md)
and [the production resource and security guide](../guides/production-resource-security.md).
