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

Exact token counters must come from a host-local normalizer with accepted
evidence for the exact host range. Fixture counters and the conservative core
fallback remain visibly estimated and do not satisfy S1/S2. See
[Host-local token accounting](../reference/host-local-token-accounting.md).

If pipeline compliance exceeds the mode limits, record why the stricter path
was needed. Do not treat an expensive lifecycle run as success by itself; the
implementation and product validation still have to pass.

The bundled reference-task suite is a synthetic, read-only comparison tool.
Its deterministic receipt exposes false acceptance and measurement gaps;
production readiness, adapter support and release promotion use their dedicated
evidence tracks.
See [Reference task evaluation](../reference/reference-task-evaluation.md).

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
- host-bound evidence for every adapter support-level promotion;
- no public marketplace or directory approval claim without external evidence;
- no host-specific semantics in shared core contracts.

Operator-local host profiles are an explicit exception to the default
no-process path, not a new source of lifecycle authority. Keep them under
ignored `.alk/host-launch/`, inspect before preflight, allow exact environment
names only, and use `start --launch` only with frozen identity and a derived
risk profile. Never put task text, shell commands or credentials in
`argvTemplate`. See [Local host launch](../reference/local-host-launch.md).
For shipped Codex, Claude Code and OpenCode profiles, require the exact-version
qualification receipt before managed launch. Version preflight is not a token
usage attestation; see [Frozen-task launch through a verified
profile](../reference/qualified-host-launch.md).

Raw-task planning is a different profile operation. It may carry task data only
over bounded stdin, must prove the host's native read-only or tool-denial
controls and must end at `REVIEW_REQUIRED`. Treat
`PLANNING_ONLY_UNSUPPORTED` as final until exact-version live containment
evidence exists; support qualification combines version preflight with live
host evidence. See
[Planning-only adapter launch](../reference/planning-only-launch.md).

Use `agent-lifecycle contract check` and release security tests before claiming
a stable package. Use the support matrix for the adapter support level; model
availability is one input to the complete `VERIFIED` evidence set.

For a source release, scan `tracked-release` so the report is bound to the Git
index and current revision. Do not add `--include-local-artifacts` to a general
release job; reserve it for a dedicated evidence step whose roots are declared
by `localArtifactRoots`. See [Neutrality scanning](../reference/neutrality.md).
