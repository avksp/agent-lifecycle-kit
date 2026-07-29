# Gemini CLI adapter

The Gemini CLI projection is an `EXPERIMENTAL` host projection scaffold. It
contains no lifecycle semantics, no concrete provider model names, and no
`VERIFIED` or production-promotion claim.

Validate the source projection before any live run:

```bash
agent-lifecycle adapter validate --descriptor adapters/gemini-cli/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/gemini-cli/adapter.descriptor.json --skip-host-commands
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --host gemini-cli --evidence <adapter-conformance-evidence.json>
```

Gemini CLI `0.46.0` has passed safe local inspection for version/help surfaces,
headless `--prompt` mode, `stream-json` output, model selection, permission
flags, skills, extensions, MCP and local Gemma routing command discovery. The
summary is `docs/adapters/evidence/gemini-cli-0.10.0.md`.

The adapter remains `EXPERIMENTAL` until live Gemini CLI conformance, usage
calibration and lifecycle proof evidence are accepted in the support matrix.
ALK now includes a bounded Gemini CLI runner and live harness that use
`--skip-trust`, `--approval-mode plan`, `--prompt`, `--output-format
stream-json` and optional `--model` to turn host output into portable
host-operation receipts.

Current blocker: `BLOCKED_UNSUPPORTED_CLIENT_TIER`; the current local Gemini
CLI 0.46.0 setup returns an unsupported Gemini Code Assist individual-client
tier error before a live receipt can be captured. No accepted Gemini CLI live
host receipt, live calibration receipt or ALK lifecycle final proof exists.
