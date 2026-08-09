# Readiness diagnostics

`agent-lifecycle diagnose` builds a redacted readiness report for the current
source checkout. It composes existing validators instead of duplicating their
rules:

- package/version consistency;
- compact-context profile validation;
- model-routing profile validation;
- adapter descriptor validation against the shared baseline;
- safe adapter inspection without live model calls by default;
- tracked redacted evidence summaries;
- declared local raw receipt availability.

```bash
agent-lifecycle diagnose
agent-lifecycle diagnose --adapter adapters/codex/adapter.descriptor.json --no-install-plans
```

The output schema is `agent-readiness-report.v1`. A `FAIL` status means a
deterministic check failed and the report includes a concrete next action. A
`WARN` status means a release-facing source artifact is missing or malformed,
or another non-mutating readiness check needs operator attention.

Verified adapter evidence is split into two classes:

- tracked redacted summaries under `docs/adapters/evidence/`;
- local raw receipts, usually under ignored `work/` paths.

The tracked summary proves what the source release can claim. Local raw receipts
are useful when re-running a live promotion review, but they may be absent from
a fresh checkout by design. `diagnose` therefore reports
`missingTrackedEvidenceSummaryCount` separately from
`missingLocalRawReceiptCount`. Missing local raw receipts alone do not turn a
source checkout into a release warning when the tracked summary is present.

Host command probes are opt-in and bounded:

```bash
agent-lifecycle diagnose --include-host-probes --timeout-seconds 5 --max-host-probes 1
```

These probes use the same safe inspection surfaces as `adapter inspect`; they
must not launch model work or produce promotion claims.

`agent-lifecycle adapter install-plan` previews setup for one adapter:

```bash
agent-lifecycle adapter install-plan --descriptor adapters/opencode/adapter.descriptor.json
```

The output schema is `agent-adapter-install-plan.v1`. The plan projects
schema-validated installation facts from the adapter descriptor: binary aliases,
files, argv arrays and operator actions. Diagnostics never interpret the argv
arrays as a shell command or execute them. It is always a dry run:

- `writesStarted: false`;
- `liveCallsStarted: false`;
- `productionPromotionClaimed: false`;
- `maturityChangeClaimed: false`.

Promotion still requires the verified-adapter release checklist: live host
conformance, usage/cost calibration, redacted evidence, and final lifecycle
proof for the exact host version.
