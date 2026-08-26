# Bounded external tool jobs

Bounded external tool jobs let an adapter run optional, longer-lived local work
and return digest-bound artifact metadata. They are useful when a specialized
auditor, analyzer or renderer cannot finish inside one synchronous external
check.

This feature is not a task queue, daemon, model runtime or workflow controller.
ALK core contains no provider client and starts no network request. The adapter
owns the executable, credentials and any network behavior; ALK only applies its
existing shell-free process boundary and validates the resulting evidence.

Ordinary workflows do not allocate external-job state. Keep using
`quality external-check` for one-shot architecture and dependency checks that
finish in the invoking process.

## Job contract

An `agent-external-job-request.v1` binds one attempt to:

- `jobId`, positive `attempt`, adapter and operation identity;
- `PROCESS` or adapter-owned `NETWORK` execution kind;
- descriptor, frozen plan, plan lock, source revision and source snapshot
  digests;
- explicit wall, attempt, output, artifact, cost, token and cancellation
  limits;
- optional parent job, parent attempt and parent request digest.

Use the contract builder so `requestDigest` is computed from the canonical
request body:

```python
from pathlib import Path

from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.contracts.external_job_schemas import build_external_job_request

request = build_external_job_request(
    job_id="dependency-audit",
    attempt=1,
    adapter_id="project-tools",
    operation="dependency-report",
    execution_kind="PROCESS",
    descriptor_digest="1" * 64,
    plan_digest="2" * 64,
    plan_lock_digest="3" * 64,
    source_revision="accepted-source-revision",
    source_snapshot_digest="4" * 64,
    limits={
        "maxWallSeconds": 120,
        "maxAttempts": 2,
        "maxOutputBytes": 65536,
        "maxArtifactBytes": 1048576,
        "maxArtifacts": 8,
        "maxCostMicros": 0,
        "maxReportedTokens": 0,
        "cancelGraceSeconds": 3,
    },
)
Path("job-request.json").write_bytes(canonical_bytes(request) + b"\n")
```

The example uses placeholder digests. A real adapter must bind the accepted
descriptor, plan, lock and source snapshot.

## Run, inspect and cancel

Pass argv after `--`; ALK never converts it to a shell command:

```bash
agent-lifecycle adapter external-job run \
  --request job-request.json \
  --out work/dependency-audit.json \
  -- python -c "print('bounded check')"

agent-lifecycle adapter external-job status \
  --request job-request.json \
  --out work/dependency-audit-status.json

agent-lifecycle adapter external-job cancel \
  --request job-request.json \
  --out work/dependency-audit-cancel.json
```

`run` is synchronous at the CLI boundary. A separate process may address the
same running attempt with `status` or `cancel`. Cancellation is idempotent and
request-digest bound. A cancellation observed before process completion wins;
a later request returns `NOT_REQUIRED` and cannot rewrite the terminal result.

The state sequence is `QUEUED`, `RUNNING`, then exactly one of `SUCCEEDED`,
`FAILED`, `CANCELLED` or `EXPIRED`. `NO_FINAL_VERDICT`, incomplete output,
failed cleanup, a live or missing declared child, a post-terminal write, stale
lineage or any exceeded limit cannot be acceptance evidence.

## Private state and recovery

The default local root is:

```text
.alk/external-jobs/<jobId>/attempt-<n>/
```

Attempt directories are create-only and reject symlinks, separators, dot
identities and path escape. On POSIX, directories are normalized to `0700` and
files to `0600`, including nested artifact directories. Existing attempts are
immutable. Recovery after interruption creates a new attempt and a new
artifact namespace; it never resumes or replaces the previous attempt.

`maxWallSeconds` bounds process execution. Cleanup may finish after that point,
so portable `wallMilliseconds` remains capped at the execution budget while
the private process receipt retains the cleanup-inclusive elapsed time. The
overrun remains an explicit blocker. This separation lets ALK persist truthful
`EXPIRED` or `CANCELLED` evidence without weakening cleanup or reporting false
success.

## Children and cleanup

A child request must name the exact parent job, parent attempt and parent
request digest. When a parent finishes, ALK sends cancellation to every
declared child and waits only for the bounded cancellation grace period. A
missing child, a child still running, failed cleanup or a post-terminal child
write blocks parent success.

The process boundary owns the whole process group. Timeout, cancellation and
output-limit paths retain cleanup evidence and do not report success while a
declared process remains live.

## Artifact evidence

The adapter writes files only below the attempt's `artifacts/` directory. ALK
stores portable records containing controlled locator, media type, byte count
and SHA-256 digest. Raw artifact bytes, stdout, argv and local absolute paths
are not portable lifecycle evidence.

Collection is bounded by count and total bytes. Stable reads reject files that
change while hashing. Symlinks, special files, path escape, oversized content
and writes observed after process completion fail closed. Rewriting the same
bytes still changes filesystem identity metadata and invalidates the result.

## Authority and qualification

External-job requests, status, results and views keep `authorityClaimed: false`
and `productionPromotionClaimed: false`. A successful job does not accept a
task, freeze a plan, authorize tools or publish a release. A frozen plan may
require independently reviewed job evidence as one acceptance input.

Adapter support must be qualified with success, real timeout, late
cancellation, process-group cleanup, terminal-parent child cancellation,
replay, stale lineage, output and artifact limits, post-terminal writes and
`NO_FINAL_VERDICT`. A descriptor or happy-path run alone is not a support
claim.
