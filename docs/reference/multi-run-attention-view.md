# Multi-run attention view

Release 2.3 adds an optional read-only projection for operators coordinating
several ALK runs. It reads only the explicitly supplied run roots and combines
bounded state, event-log, evidence-index and declared ownership facts.

## Command

```bash
agent-lifecycle report multi-run \
  --project-root . \
  --run-root work/release-a \
  --run-root work/release-b \
  --out work/multi-run-view.json
```

Use `--max-runs` and `--max-bytes-per-run`; the event-record limit is fixed and
reported in the returned `limits` object. Use `--now
2026-08-25T00:00:00Z` when a reproducible stale-attempt decision is needed in a
test or review. The `attention` report alias is also accepted.

The result uses `agent-multi-run-attention-view.v1`. Attention items carry a
run ID, plan revision, source revision, state revision and a stable reason
code. Reason codes include blockers, required user action, pending review,
stale attempts, failed evidence and terminal runs. A malformed or inaccessible
source is represented as `SOURCE_UNAVAILABLE`; it is never treated as a
successful run.

## Overlap and authority

Declared ownership or changed-file paths shared by selected runs appear in
`overlaps` with `authorityRetained: true`. This is an advisory conflict signal:
the command does not choose an owner, merge files, authorize a task, resolve a
conflict or change workflow state. The frozen plan and its workflow state remain
the only authority.

The command rejects roots outside `--project-root`, symlinked components,
invalid repository-relative paths and inputs over the configured byte or record
limits. Output is redacted and deterministically ordered. With no `--run-root`,
the command returns an empty PASS view and does not create a file or scan the
project.

The feature does not start a model, host process, network request, daemon,
database or scheduler. It is an operator report, not a multi-agent
orchestrator.
