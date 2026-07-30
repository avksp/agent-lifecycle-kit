# Diagnostic bundles

Diagnostic bundles export a redacted, compact summary from existing lifecycle
artifacts. `agent-diagnostic-bundle.v1` includes artifact identities, schema
versions, status values, blocker counts and redacted summary digests. It does
not copy full evidence payloads into a new source of truth.

The bundle command is opt-in, read-only for input artifacts and capped by
artifact count and input bytes. It fails closed when an artifact is missing,
malformed, too large or when redaction leaks the checkout path.

```bash
agent-lifecycle diagnostics bundle --artifact <evidence.json> --out <diagnostic-bundle.json>
```

Use the bundle to give a small local model enough context for routing or
triage. Final acceptance should still inspect the original plan, receipt and
review artifacts.
