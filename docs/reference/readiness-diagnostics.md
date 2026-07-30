# Readiness diagnostics

`agent-lifecycle diagnose` builds a redacted readiness report for the current
source checkout. It composes existing validators instead of duplicating their
rules:

- package/version consistency;
- compact-context profile validation;
- model-routing profile validation;
- adapter descriptor validation against the shared baseline;
- safe adapter inspection without live model calls by default;
- declared live evidence availability.

```bash
agent-lifecycle diagnose
agent-lifecycle diagnose --adapter adapters/codex/adapter.descriptor.json --no-install-plans
```

The output schema is `agent-readiness-report.v1`. A `WARN` status can still be
actionable, for example when verified adapter descriptors reference local-only
evidence under `work/`. A `FAIL` status means a deterministic check
failed and the report includes a concrete next action.

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

The output schema is `agent-adapter-install-plan.v1`. The plan records files,
commands and operator actions, but it is always a dry run:

- `writesStarted: false`;
- `liveCallsStarted: false`;
- `productionPromotionClaimed: false`;
- `maturityChangeClaimed: false`.

Promotion still requires the verified-adapter release checklist: live host
conformance, usage/cost calibration, redacted evidence, and final lifecycle
proof for the exact host version.
