# Read-Only Status Views

Read-only status views render a compact status summary from existing artifacts.
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
