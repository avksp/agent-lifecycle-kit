# Production resource and security guide

ALK should help finish the user's task with evidence, not spend most of the run
proving its own process. Use the lightest lifecycle mode that still matches
task risk.

## Resource mode

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

Exact token counters must come from a qualified host-local normalizer. Fixture
counters and the conservative core fallback remain visibly estimated and do
not satisfy S1/S2. See
[Host-local token accounting](../reference/host-local-token-accounting.md).

If pipeline compliance exceeds the mode limits, record why the stricter path
was needed. Do not treat an expensive lifecycle run as success by itself; the
implementation and product validation still have to pass.

## Small local models

Small models should receive compact snapshots and receipts first:

- `goal summarize` for intent and next action;
- `runner status --target-window 4k-strict` for execution state;
- `report status-view --target-window 4k-strict` for redacted evidence status;
- `metrics cost-check` for process overhead.

These compact artifacts guide execution. They do not replace full evidence for
final review.

## External context

External memory exports are optional hints, not authority:

```bash
agent-lifecycle context external-import \
  --source work/context/project-memory.md \
  --citation "operator-approved project memory export" \
  --out work/context/project-memory.external-context.json
```

Only import files that the operator has chosen explicitly. ALK does not call
MCP servers, RAG services, providers or host CLIs to fetch memory. Receipts must
keep `sourceOfTruth: false`, redact secret-like values and avoid private local
paths.

## Security boundary

Release and production checks must keep these boundaries:

- no private keys, tokens, cookies or local machine paths in tracked files;
- no external memory as lifecycle proof or source of truth;
- no adapter maturity promotion without host-bound evidence;
- no public marketplace or directory approval claim without external evidence;
- no host-specific semantics in shared core contracts.

Use `agent-lifecycle contract check` and release security tests before claiming
a stable package. Use the support matrix for adapter maturity; model availability
alone is not enough to mark an adapter `VERIFIED`.

For a source release, scan `tracked-release` so the report is bound to the Git
index and current revision. Do not add `--include-local-artifacts` to a general
release job; reserve it for a dedicated evidence step whose roots are declared
by `localArtifactRoots`. See [Neutrality scanning](../reference/neutrality.md).
