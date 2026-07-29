# qwen-code adapter

The qwen-code projection is `VERIFIED` for qwen-code `0.21.0` on the tested
local GLM 5.2 binding. This is a host-specific source-tree compatibility claim,
not a public package, public directory approval, or production-promotion
platform claim. It does not claim public approval. The adapter has accepted
live conformance evidence.

Validate the projection and live evidence:

```bash
agent-lifecycle adapter validate --descriptor adapters/qwen-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/qwen-code/adapter.descriptor.json --skip-host-commands
python tools/release/validate_live_host_conformance.py --profile conformance/core/live-calibration-profile.v1.json --baseline conformance/core/adapter-baseline.v1.json --receipt-dir tasks/release-0-11/evidence/qwen-code/live-host-receipts --promoted-hosts qwen-code --evidence <live-host-conformance-qwen-code.json>
python tools/release/validate_live_calibration.py --profile conformance/core/live-calibration-profile.v1.json --budget-targets conformance/core/budget-targets.v1.json --receipt-dir tasks/release-0-11/evidence/qwen-code/live-calibration-receipts --promoted-hosts qwen-code --evidence <live-calibration-verification-qwen-code.json>
```

Live evidence accepted on 2026-07-29:

- qwen-code version: `0.21.0`;
- model binding used by the live harness: GLM 5.2;
- live host conformance: 13/13 baseline operations passed;
- live calibration: 14/14 scenario/cohort runs passed;
- quality regression count: 0;
- ALK lifecycle proof:
  `tasks/release-0-11/evidence/qwen-code/full-lifecycle/final/final-proof.json`.

The live runner is `adapters/qwen-code/runner.py`. The release harness is
`tools/live_hosts/qwen_code_harness.py`; it runs qwen in `--safe-mode` with
`--output-format stream-json`, enforces invocation/token/wall-clock budget
guards, normalizes usage into portable host-operation receipts, and fails
closed when qwen output is missing usage attestation.

Evidence summaries:

- Historical scaffold/smoke note:
  `docs/adapters/evidence/qwen-code-0.11.0.md`;
- live promotion note:
  `docs/adapters/evidence/qwen-code-glm52-live-2026-07-29.md`;
- support matrix entry:
  `docs/adapters/support-matrix.md`.
