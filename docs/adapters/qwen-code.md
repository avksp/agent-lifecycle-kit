# Qwen Code adapter

The Qwen Code projection is `VERIFIED` for Qwen Code `0.21.0` on the tested
host-local provider/model binding. The adapter has accepted live conformance
evidence for this exact integration range.

Validate the projection and live evidence:

```bash
agent-lifecycle adapter validate --descriptor adapters/qwen-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/qwen-code/adapter.descriptor.json --skip-host-commands
python tools/release/validate_live_host_conformance.py --profile conformance/core/live-calibration-profile.v1.json --baseline conformance/core/adapter-baseline.v1.json --receipt-dir work/release-0-11/evidence/qwen-code/live-host-receipts --promoted-hosts qwen-code --evidence <live-host-conformance-qwen-code.json>
python tools/release/validate_live_calibration.py --profile conformance/core/live-calibration-profile.v1.json --budget-targets conformance/core/budget-targets.v1.json --receipt-dir work/release-0-11/evidence/qwen-code/live-calibration-receipts --promoted-hosts qwen-code --evidence <live-calibration-verification-qwen-code.json>
```

Live evidence accepted on 2026-07-29:

- Qwen Code version: `0.21.0`;
- provider/model binding used by the live harness: host-local and redacted in
  committed docs;
- live host conformance: 13/13 baseline operations passed;
- live calibration: 14/14 scenario/cohort runs passed;
- quality regression count: 0;
- ALK lifecycle proof:
  `work/release-0-11/evidence/qwen-code/full-lifecycle/final/final-proof.json`.

The live runner is `adapters/qwen-code/runner.py`. The release harness is
`tools/live_hosts/qwen_code_harness.py`; it runs qwen in `--safe-mode` with
`--output-format stream-json`, enforces invocation/token/wall-clock budget
guards, normalizes usage into portable host-operation receipts, and fails
closed when qwen output is missing usage attestation.

Qwen Code support level and the newly factored token parser have separate
evidence. The adapter is `VERIFIED`, while
`usageNormalization.status: FIXTURE_ONLY` keeps new sidecars `ESTIMATED` until
that parser is independently qualified for a live host range. See
[Host-local token accounting](../reference/host-local-token-accounting.md).

Evidence summaries:

- Historical scaffold/smoke note:
  `docs/adapters/evidence/qwen-code-0.11.0.md`;
- live promotion note:
  `docs/adapters/evidence/qwen-code-host-local-live-2026-07-29.md`;
- support matrix entry:
  `docs/adapters/support-matrix.md`.

## Planning-only launch status

Exact-version profile: `0.21.8`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The qualification path includes a native
read-only or tool-denial boundary for this contract.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter qwen-code --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/qwen-code.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/qwen-code.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/qwen-code.json
```

The planning route uses the status and evidence described in [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with Qwen Code

The documented Qwen Code route is the terminal command. A separately reviewed
Qwen Code configuration can expose the shared skills:

```bash
agent-lifecycle start --adapter qwen-code --file task.md
```

The command creates ALK intake. For host execution, use the launch route through
a verified profile. See [Using ALK with an adapter](usage-modes.md).
