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

The adapter-local `stream-json` usage normalizer is `FIXTURE_ONLY`. Runner and
harness use the same bounded parser, but its sidecar remains `ESTIMATED` and
cannot satisfy S1/S2 until a live Gemini CLI range is qualified. See
[Host-local token accounting](../reference/host-local-token-accounting.md).

Current blocker: `BLOCKED_UNSUPPORTED_CLIENT_TIER`; the current local Gemini
CLI 0.46.0 setup returns an unsupported Gemini Code Assist individual-client
tier error before a live receipt can be captured. No accepted Gemini CLI live
host receipt, live calibration receipt or ALK lifecycle final proof exists.

## Planning-only launch status

Exact-version profile: `0.46.0`. Profile status: `CANDIDATE`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The plan approval mode and stdin route form a static candidate, but no accepted live containment evidence is shipped.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter gemini-cli --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/gemini-cli.json
```

A successful version preflight does not authorize planning launch.
`managedLaunch.status` remains `WRAPPER_ONLY`, and adapter maturity cannot
promote planning support. See [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with Gemini CLI

Gemini CLI can discover skills, but the bundled adapter does not modify the
host skill directory. Configure the tagged shared `skills/` directory through
Gemini CLI's native settings and request `agent-workflow-orchestrator`, or use
the supported command route:

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle through reviewed planning, plan freeze,
implementation audits and accepted final proof.
Task: <describe the task or name the Markdown file to read>
```

The request above applies only after that host-local skill configuration.

```bash
agent-lifecycle start --adapter gemini-cli --file task.md
```

Without explicit host skill configuration, the command route is canonical. It
does not start Gemini CLI by default. See [Using ALK with an
adapter](usage-modes.md).
