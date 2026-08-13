# Gemini CLI adapter

The Gemini CLI projection is an `EXPERIMENTAL` host integration with a
descriptor, conformance commands, a bounded runner and lifecycle evidence
routes. Provider and model selection stays in the host configuration.

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

The support level is `EXPERIMENTAL`. ALK includes a bounded Gemini CLI runner
and live harness that use
`--skip-trust`, `--approval-mode plan`, `--prompt`, `--output-format
stream-json` and optional `--model` to turn host output into portable
host-operation receipts.

The adapter-local `stream-json` usage normalizer is `FIXTURE_ONLY`. Runner and
harness use the same bounded parser, while the sidecar is recorded as
`ESTIMATED` until a live Gemini CLI range is qualified. See
[Host-local token accounting](../reference/host-local-token-accounting.md).

The current local Gemini CLI 0.46.0 setup is recorded as
`BLOCKED_UNSUPPORTED_CLIENT_TIER`. Qualification continues with a supported
Gemini Code Assist client tier, followed by live host, calibration and
lifecycle receipts.

## Planning-only launch status

Exact-version profile: `0.46.0`. Profile status: `CANDIDATE`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The plan approval mode and stdin route form a static candidate, but no accepted live containment evidence is shipped.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter gemini-cli --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/gemini-cli.json
```

The profile status and support matrix determine planning launch eligibility.
`managedLaunch.status` is `WRAPPER_ONLY`; the qualification sequence is in
[Planning-only adapter launch](../reference/planning-only-launch.md).

## Use ALK with Gemini CLI

Configure the tagged shared `skills/` directory through Gemini CLI's native
settings and request `agent-workflow-orchestrator`, or use the supported
command route:

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle through reviewed planning, plan freeze,
implementation audits and accepted final proof.
Task: <describe the task or name the Markdown file to read>
```

After configuring the host-local skills, use the request above inside the
session.

```bash
agent-lifecycle start --adapter gemini-cli --file task.md
```

The command route is the canonical terminal entrypoint. Add a verified launch
profile when the task requires a host process. See [Using ALK with an
adapter](usage-modes.md).
