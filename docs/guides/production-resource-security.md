# Production Resource And Security Guide

ALK should help finish the user's task with evidence, not spend most of the run
proving its own process. Use the lightest lifecycle mode that still matches
task risk.

## Resource Mode

- Use `light` for small, low-risk edits with narrow ownership and quick checks.
- Use `standard` for ordinary feature and bug-fix work.
- Use `strict` when security, data loss, public API compatibility or difficult
  review quality matters.
- Use `release` when package metadata, release notes, tags or publication
  artifacts are part of the task.

Every mode can still use compact context receipts, model usage receipts and
runner caps. Higher modes add more evidence, but they should not hide the cost:

```bash
agent-lifecycle metrics cost-check --receipt <lifecycle-cost-report.json>
```

If pipeline compliance exceeds the mode limits, record why the stricter path
was needed. Do not treat an expensive lifecycle run as success by itself; the
implementation and product validation still have to pass.

## Small Local Models

Small models should receive compact snapshots and receipts first:

- `goal summarize` for intent and next action;
- `runner status --target-window 4k-strict` for execution state;
- `report status-view --target-window 4k-strict` for redacted evidence status;
- `metrics cost-check` for process overhead.

These compact artifacts guide execution. They do not replace full evidence for
final review.

## Security Boundary

Release and production checks must keep these boundaries:

- no private keys, tokens, cookies or local machine paths in tracked files;
- no adapter maturity promotion without host-bound evidence;
- no public marketplace or directory approval claim without external evidence;
- no host-specific semantics in shared core contracts.

Use `agent-lifecycle contract check` and release security tests before claiming
a stable package. Use the support matrix for adapter maturity; model availability
alone is not enough to mark an adapter `VERIFIED`.
