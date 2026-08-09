# Usage Export

`agent-lifecycle metrics usage-export` builds a read-only export from explicit
local JSON artifacts. It does not start host calls and it does not estimate
money for local models.

The export records:

- adapter, session, run, task and operation ids;
- receipt digests discovered in source artifacts;
- input, output and total tokens;
- step counts, durations and resource units such as context bytes or tool calls;
- optional budget decisions;
- optional `cost_usd` only when a metered host reports it.
- `usageConfidence`: `ATTESTED`, `ESTIMATED`, `MISSING` or `INVALID`.

`ATTESTED` requires both `attestation.source: host` and
`attestation.status: ATTESTED`. A core estimate or fixture receipt remains
`ESTIMATED` even when it contains exact numeric counters for its own input.

`cost_usd` is metadata, not canonical accounting. Token and resource totals are
the portable common layer. The core has no built-in rate catalog and does not
convert local-model usage into money.

Examples:

```bash
agent-lifecycle metrics usage-export \
  --artifact work/run/model-usage.json \
  --project-root . \
  --format json \
  --out work/run/usage-export.json

agent-lifecycle metrics usage-export \
  --artifact work/run/model-usage.json \
  --format table \
  --out work/run/usage-export.txt
```

Outputs are write-once. String fields copied from source artifacts are redacted
for local absolute paths and common secret markers before validation.

See [Host-local token accounting](host-local-token-accounting.md) for adapter
normalizer status and S1/S2 acceptance rules.
