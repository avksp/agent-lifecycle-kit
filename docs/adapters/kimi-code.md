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

Current support level: `EXPERIMENTAL`. The qualification path adds live Kimi
Code conformance, usage calibration and lifecycle proof evidence.
The bounded harness uses headless `--prompt` with post-invocation clean-worktree
checks; Kimi Code uses a separate plan permission route.
Its adapter-local `stream-json` usage normalizer is `FIXTURE_ONLY`: runner and
harness share the bounded parser, while S1/S2 qualification uses a host-attested
sidecar. See
[Host-local token accounting](../reference/host-local-token-accounting.md).
Current qualification state: `BLOCKED_HOST_MODEL_NOT_CONFIGURED`. Configure a
provider and model alias to capture usage-attested host, calibration and
lifecycle receipts for Kimi Code `0.30.0`.

## Planning-only launch status

Exact-version profile: `0.30.0`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The qualification path uses a verified
bounded stdin result transport and containment evidence.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter kimi-code --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/kimi-code.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/kimi-code.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/kimi-code.json
```

The planning route uses the status and evidence described in [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Lifecycle-control status

For Kimi Code, every operation in the descriptor (`cancel`, `discover`, `final-audit`, `install`, `launch`, `model-route-execution`, `result-collection`, `resume`, `task-audit`, `tool-execution`, `adapter-event-stream`, `usage-attestation`, `validate-envelope`, `wait`) publishes
`declaredLevel: GUIDANCE_ONLY`, `supportedLevel: GUIDANCE_ONLY`,
`qualifiedLevel: GUIDANCE_ONLY` and `qualificationStatus: NO_RECOMMENDATION`.
The managed-launch status is `WRAPPER_ONLY`. These are operation-level
lifecycle-control claims and are separate from the general adapter support
level in the matrix.

The page and the adapter skill describe how to follow ALK inside the host. They
do not claim that a prompt, plugin or wrapper blocks an action. An exact-version
host-owned producer may be qualified later for selected operations; offline
fixtures alone do not promote the level. See [optional adapter lifecycle
control](lifecycle-control.md) and [using ALK with an adapter](usage-modes.md).

## Use ALK with Kimi Code

Kimi Code exposes skill-directory selection. Configure the tagged shared
`skills/` directory through the host, then request
`agent-workflow-orchestrator`, or use:

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle through reviewed planning, plan freeze,
implementation audits and accepted final proof.
Task: <describe the task or name the Markdown file to read>
```

The request above applies only after that host-local skill configuration.

```bash
agent-lifecycle start --adapter kimi-code --file task.md
```

The command route creates ALK intake. For host execution, use the qualified
launch route. See [Using ALK with an adapter](usage-modes.md).
