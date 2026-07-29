# qwen-code adapter

The qwen-code projection is an `EXPERIMENTAL` host projection scaffold. It
contains no lifecycle semantics, no concrete provider model names, and no
`VERIFIED` or production-promotion claim.

Validate the source projection before any live run:

```bash
agent-lifecycle adapter validate --descriptor adapters/qwen-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/qwen-code/adapter.descriptor.json --skip-host-commands
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --host qwen-code --evidence <adapter-conformance-evidence.json>
```

qwen-code `0.21.0` has passed safe local inspection for version/help surfaces,
headless `--prompt` mode, `stream-json` output, model and fallback model
selection, sandbox/safe-mode permission controls, resume/session discovery, MCP
management, and extensions. The summary is
`docs/adapters/evidence/qwen-code-0.11.0.md`.

The adapter remains `EXPERIMENTAL` until live qwen-code conformance, usage
calibration and lifecycle proof evidence are accepted in the support matrix.
Current blocker: `BLOCKED_LIVE_HARNESS_NOT_IMPLEMENTED`; additionally, the
inspected root CLI help did not expose bounded wall-time or tool-call cap flags,
so the future live harness must enforce those caps outside the host if the host
does not add native limits.
