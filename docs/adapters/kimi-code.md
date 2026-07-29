# Kimi Code adapter

The Kimi Code projection is an `EXPERIMENTAL` host projection scaffold. It
contains no lifecycle semantics, no concrete provider model names, and no
production-promotion claim. It is not `VERIFIED`.

Validate the source projection before any live run:

```bash
agent-lifecycle adapter validate --descriptor adapters/kimi-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/kimi-code/adapter.descriptor.json --skip-host-commands
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --host kimi-code --evidence <adapter-conformance-evidence.json>
```

Kimi Code `0.30.0` has passed safe local inspection through the local `kimi`
CLI for version/help surfaces, headless `--prompt` mode, `stream-json` output,
model selection, yolo/auto/plan permission controls, skills directory
selection, provider discovery, session export, ACP stdio server discovery, and
configuration validation. The summary is
`docs/adapters/evidence/kimi-code-0.12.0.md`.

The adapter remains `EXPERIMENTAL` until live Kimi Code conformance, usage
calibration and lifecycle proof evidence are accepted in the support matrix.
Current blocker: `BLOCKED_LIVE_HARNESS_NOT_IMPLEMENTED`; usage attestation is
still unproven until a bounded live harness normalizes `stream-json` output into
portable host-operation receipts.
