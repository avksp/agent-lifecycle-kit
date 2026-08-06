# External memory

External memory support lets an operator import a local exported context file as
an optional hint for episode retrieval. The imported file can come from an MCP
tool, a notes system, a previous agent workspace or another local source, but
ALK does not call that source itself.

## Safe import

```bash
agent-lifecycle context external-import \
  --source work/context/project-memory.md \
  --citation "operator-approved project memory export" \
  --out work/context/project-memory.external-context.json
```

The command emits `agent-external-context-import-receipt.v1`. The receipt keeps
the source digest, citation, redaction status and a bounded sanitized hint. It
sets `sourceOfTruth: false`, `rawContentStored: false`,
`modelCallsStarted: false`, `networkCallsStarted: false` and
`providerApiCallsStarted: false`.

## Episode retrieval

```bash
agent-lifecycle context episode-retrieve \
  --project-root . \
  --artifact work/run/final-proof.json \
  --external-context work/context/project-memory.external-context.json \
  --query "regression proof" \
  --out work/context/episode-retrieval.json
```

External context appears under `externalContextHints`. It is not mixed into the
episode results. It cannot satisfy evidence, review or final proof requirements.

## Boundaries

- External context is optional and disabled unless imported explicitly.
- ALK reads local files only; it does not call MCP servers, RAG services,
  providers or host CLIs.
- Secret-like values and local absolute paths are redacted before receipt
  storage.
- External context can guide planning or review, but only lifecycle receipts,
  reviews, validation output and final proof can close acceptance.
