# Read-only status views

Read-only status views render compact summaries from existing artifacts.
`agent-readonly-status-view.v1` records that the view is not source of truth,
lists source artifact identities and reports status counts, blocker codes and
next actions.

The view is useful when a small local model needs a short status packet before
deciding whether to continue, inspect failed evidence or ask for a stronger
review. Larger models can still inspect the original artifacts.

```bash
agent-lifecycle report status-view --artifact <evidence.json> --target-window 4k-strict
```

Malformed or failed source artifacts make the view fail closed. The command
does not run host code, change adapter maturity or claim production promotion.

## Workflow event feed

`agent-workflow-event-feed.v1` projects `agent-workflow-state.v3` into a
deterministic event list. It is read-only, does not write workflow state, does
not start host code and does not perform model calls.

```bash
agent-lifecycle report event-feed --state <workflow-state.json>
```

The feed is for review and progress displays. Workflow state remains the source
of truth.

## Lifecycle progress

`agent-lifecycle-progress-view.v1` renders fixed-width one-line lifecycle rows
from workflow state, optional attested usage receipts and an optional change
summary. The projection spends no tokens; unknown or unattested token usage is
shown as `↑?/↓? tok`.

Example terminal output:

```text
implementation         DONE       00:01:05 ↑0.2k/↓1.1k tok 7 files · +432 -118
TOTAL                  DONE       00:01:05 ↑0.2k/↓1.1k tok 7 files changed · 432 insertions · 118 deletions · 5 modified · 1 added · 1 deleted
```

```bash
agent-lifecycle report progress --state <workflow-state.json> \
  --usage-receipt <usage.json> \
  --change-summary <changes.json>
```

Change summaries use git-style counters: files changed, insertions, deletions,
modified, added and deleted. The command never runs `git`; callers provide a
summary artifact when they want those counters displayed.
