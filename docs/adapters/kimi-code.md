# Kimi Code adapter

The Kimi Code projection is an `EXPERIMENTAL` host projection with a bounded
runner and live harness. It contains no portable provider model names and no
production-promotion claim. It is not `VERIFIED`.

Validate the source projection before any live run:

```bash
agent-lifecycle adapter validate --descriptor adapters/kimi-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/kimi-code/adapter.descriptor.json --skip-host-commands
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --host kimi-code --evidence <adapter-conformance-evidence.json>
python tools/live_hosts/kimi_code_harness.py --mode fixture-check --baseline conformance/core/adapter-baseline.v1.json --report <kimi-code-fixture-check.json>
python tools/live_hosts/kimi_code_harness.py --mode preflight --baseline conformance/core/adapter-baseline.v1.json --budget-mode subscription --max-invocations 1 --report <kimi-code-preflight-report.json>
```

Kimi Code `0.30.0` has passed safe local inspection through the local `kimi`
CLI for version/help surfaces, headless `--prompt` mode, `stream-json` output,
model selection, yolo/auto/plan permission controls, skills directory
selection, provider discovery, session export, ACP stdio server discovery, and
configuration validation. The summary is
`docs/adapters/evidence/kimi-code-0.12.0.md`.

The adapter remains `EXPERIMENTAL` until live Kimi Code conformance, usage
calibration and lifecycle proof evidence are accepted in the support matrix.
The bounded harness uses headless `--prompt` with post-invocation clean-worktree
checks because Kimi Code does not allow `--prompt` and `--plan` together.
Current blocker: `BLOCKED_HOST_MODEL_NOT_CONFIGURED`; the current local Kimi
Code 0.30.0 setup has no configured providers/model aliases, so no
usage-attested live host receipt, calibration receipt, or lifecycle final proof
can be captured yet.
