# Adapter install

Adapter setup follows two steps:

1. Validate and inspect source metadata.
2. Apply host-local installation commands only after operator review.

To get started, begin with [Install ALK and make the first run](../guides/install-and-first-run.md).
This page is the adapter-specific reference.

Choose the route that matches the host workflow. See [Using ALK with an
adapter](usage-modes.md) for the difference between loading ALK skills inside a
  host, running `agent-lifecycle` from the project terminal and explicitly
  launching through a verified profile.

Use the dry-run planner first:

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

The planner records the installation preview, live-call state and support level
state in its receipt.

## Common checks

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json \
  --skip-host-commands
```

`adapter inspect` is a safe source and command-surface check. Live host
conformance uses the host-specific evidence route in the support matrix.

## Publication channels

Install from immutable semantic-version refs by default. Root plugin manifests
and adapter-local plugin projections must declare the real semver in `version`.
Marketplace source refs use `source.ref: vX.Y.Z` when the host installs from a
repository tag.

A floating `last` channel, when supported by a host, is an opt-in source ref
that points to an accepted release commit. Semantic version remains the
canonical value inside `plugin.json`.

## Updating an installed plugin

An exact Codex marketplace ref is pinned. `codex plugin marketplace upgrade`
refreshes the configured source at that ref. To update Codex to a new accepted
release, replace the pinned marketplace source and reinstall the plugin:

```bash
codex plugin remove agent-lifecycle-kit@agent-lifecycle-kit
codex plugin marketplace remove agent-lifecycle-kit
codex plugin marketplace add https://github.com/avksp/agent-lifecycle-kit.git --ref vX.Y.Z
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
codex plugin list
```

Claude Code uses marketplace refresh and plugin update commands instead of a
`--ref` option on `plugin marketplace add`:

```bash
claude plugin marketplace update agent-lifecycle-kit
claude plugin update agent-lifecycle-kit@agent-lifecycle-kit
claude plugin list
```

Restart the host session after either update so it loads the new plugin skills
and metadata. Verify the reported installed version before starting managed
work.

## Host-local secrets

Adapters that call a real model should receive credentials through the host's
normal mechanism: environment variables, the host credential store or an
operator-managed secret launcher. ALK stores provider-neutral, redacted metadata
in tracked config, descriptors, receipts and release evidence; provider keys
remain in the host credential mechanism.

For live harnesses, use `--host-env-file` only as a scoped process-launch
helper when you do not want to export a key globally. The file is a private
dotenv-style operator file outside the repository, and each variable must be
explicitly allowed for that harness invocation:

```bash
python tools/live_hosts/<host>_harness.py \
  --mode preflight \
  --host-env-file ~/.config/alk/hosts/<host>.env \
  --host-env-allow PROVIDER_API_KEY \
  --report work/<release>/evidence/<host>-preflight.json
```

The harness passes the allowed names to the child host process and records
`agent-host-env-file-redacted.v1` metadata. `tools/release/validate_host_env_hygiene.py`
checks that the secret value is absent from reports and receipts.

This rule applies to every provider-flexible adapter. If the host can switch
providers or models, the selected provider remains responsible for the
credential name and source; ALK only receives the operator-approved variable
name for the current harness run.

## Managed lifecycle handoff

Hosts that want one deterministic lifecycle loop can call
`agent-lifecycle workflow run` before launching work. The command returns the
next action and fail-closed blockers. Adapters remain responsible
for native launches, waits, cancellation and telemetry.

For an ALK-owned entrypoint around adapter sessions, use
`agent-lifecycle adapter session start/status/resume/promote` or
`agent-lifecycle adapter run`. These commands produce
`agent-adapter-session-receipt.v1` and
`agent-adapter-session-resume-receipt.v1` receipts, bind managed runs to frozen
workflow state, and keep plugin installation separate from lifecycle proof. The
current bundled adapters declare `managedLaunch.status: WRAPPER_ONLY`; qualified
profiles provide the accepted frozen-task launch route. See
`docs/adapters/managed-session-support.md`.

## Adapter progress bridge

Adapters can expose progress without changing the lifecycle state. Use
`agent-lifecycle report progress-bridge` for a stable
`agent-progress-bridge-receipt.v1`, or `agent-lifecycle report progress
--terminal` for a one-shot terminal line. Support levels are tracked in
`docs/adapters/progress-bridge-matrix.md`; the adapter support level remains a
separate evidence claim.

ALK-managed workflow commands can also emit progress directly when called with
`--progress-hook stderr`, or persist `agent-progress-hook-receipt.v1` with
`--progress-hook receipt --progress-receipt <path>`. This route is opt-in;
lifecycle proof is formed by the resulting state transitions and accepted
receipts.

## Codex

Files:

- `.codex-plugin/plugin.json`
- `.agents/plugins/marketplace.json`
- `skills/`

Operator flow:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref vX.Y.Z
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

Restart the host session after installation. Codex is host-specific `VERIFIED`
only for the tested Codex CLI range in the support matrix.

Progress bridge: after `workflow run` or a workflow transition, a Codex wrapper
can call `agent-lifecycle report progress-bridge --adapter codex --support-level
WATCH --hook-point side-terminal-watch --state <state> --terminal` and render
the returned lines locally. Pass host-attested usage receipts with
`--usage-receipt` and a Git change summary with `--change-summary` when those
artifacts exist; token counts come from the host receipt.

## Claude Code

Files:

- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `skills/`

Operator flow:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

Reload the host session after installation. Claude Code is host-specific
`VERIFIED` only for the tested range in the support matrix.

Progress bridge: invoke `agent-lifecycle report progress --state <state>` after
lifecycle transitions, or bounded `--watch` while the run is active. Claude Code
keeps native telemetry collection; ALK only reads supplied receipts.

## Cursor

Files:

- `.cursor-plugin/plugin.json`
- `.cursor-plugin/marketplace.json`
- `adapters/cursor/*`
- `skills/`

Cursor has `EXPERIMENTAL` support. Local linking provides manual inspection and
the qualification starting point:

```bash
ln -s <checkout> ~/.cursor/plugins/local/agent-lifecycle-kit
```

Progress bridge: Cursor documents `MANUAL` support. Run
`agent-lifecycle report progress --state <state> --terminal` after ALK workflow
transitions; support qualification uses its own evidence route.

## OpenCode

Files:

- `opencode.json`
- `adapters/opencode/plugins/agent-lifecycle-kit.js`
- `skills/`

Operator flow depends on whether the user wants project-level or user-level
configuration. The dry-run install plan shows the exact source files to copy or
link. OpenCode is host-specific `VERIFIED` only for the tested range in the
support matrix.

Progress bridge: OpenCode integrations should render ALK progress from
`agent-lifecycle report progress-bridge --adapter opencode --support-level WATCH
--hook-point side-terminal-watch` and keep provider or model telemetry
normalization in the OpenCode-side adapter.

## Hermes

Files:

- `skills.sh.json`
- `adapters/hermes/hermes.registry.json`
- `adapters/hermes/slash-commands.json`
- `skills/`

Install the tagged lifecycle skills accepted by the operator:

```bash
hermes skills install https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/vX.Y.Z/skills/agent-workflow-orchestrator/SKILL.md
```

Repeat for each required lifecycle skill. Hermes is host-specific `VERIFIED`
only for the tested range in the support matrix.

Progress bridge: Hermes documents `MANUAL` support. Run
`agent-lifecycle report progress --state <state> --terminal` after workflow
transitions.

## Qwen Code

Files:

- `adapters/qwen-code/adapter.descriptor.json`
- `adapters/qwen-code/capabilities.manifest.json`
- `adapters/qwen-code/runner.py`
- `adapters/qwen-code/receipt_normalizer.py`

Confirm the host CLI before live proof:

```bash
qwen --version
agent-lifecycle adapter inspect \
  --descriptor adapters/qwen-code/adapter.descriptor.json \
  --skip-host-commands
```

Qwen Code is host-specific `VERIFIED` only for the tested host-local
provider/model binding and host range in the support matrix.

Progress bridge: Qwen Code documents `MANUAL` support. Run the bridge after ALK
workflow transitions; model telemetry remains host-local.

## Gemini CLI

Files:

- `adapters/gemini-cli/adapter.descriptor.json`
- `adapters/gemini-cli/capabilities.manifest.json`
- `adapters/gemini-cli/runner.py`
- `adapters/gemini-cli/receipt_normalizer.py`

Confirm the host CLI:

```bash
gemini --version
```

Gemini CLI has `EXPERIMENTAL` support. Qualification adds live conformance,
usage calibration and lifecycle proof for a concrete host range.

Progress bridge: Gemini CLI documents `MANUAL` support. The progress route is
separate from support-level qualification.

## Goose

Files:

- `adapters/goose/adapter.descriptor.json`
- `adapters/goose/capabilities.manifest.json`

Confirm the host CLI and keep the ACP probe fail-closed:

```bash
goose --help
agent-lifecycle adapter install-plan --descriptor adapters/goose/adapter.descriptor.json
```

Goose is host-specific `VERIFIED` only for Goose `1.45.0` on the tested
host-local provider/model binding. Live promotion used bounded
no-session/no-profile invocations with explicit provider/model selection and
clean-worktree checks.

Progress bridge: Goose can use `WATCH` support from a side terminal or wrapper.
ACP support remains separately probe-gated.

## Kimi Code

Files:

- `adapters/kimi-code/adapter.descriptor.json`
- `adapters/kimi-code/capabilities.manifest.json`
- `adapters/kimi-code/runner.py`
- `adapters/kimi-code/receipt_normalizer.py`

Load any host-local shell configuration before probing when required by the
operator environment:

```bash
source ~/.zshrc
kimi --version
```

Kimi Code has `EXPERIMENTAL` support. Qualification uses provider/model
configuration, live conformance, usage calibration and lifecycle proof.

Progress bridge: Kimi Code documents `MANUAL` support. The progress route is
separate from support-level qualification.

## Grok Build

```bash
grok --version
grok agent --help
agent-lifecycle adapter install-plan --descriptor adapters/grok-build/adapter.descriptor.json
```

Grok Build has host-specific `VERIFIED` support for Grok Build `0.2.117` on the
tested host-local provider/model binding. The ACP path remains probe-gated, and
a failed probe is recorded as fail-closed evidence.

Progress bridge: Grok Build can use `WATCH` support from a side terminal or
wrapper after Grok-side lifecycle steps.

## OpenInterpreter

```bash
interpreter --version
interpreter doctor --json
agent-lifecycle adapter install-plan --descriptor adapters/openinterpreter/adapter.descriptor.json
```

OpenInterpreter has host-specific `VERIFIED` support for `interpreter` 0.0.34
on the tested host-local provider/model binding. The selected model
credentials must be visible to the `interpreter` process before a local live
rerun can start. OpenInterpreter chooses the required variable from the selected
provider: custom providers declare `env_key` in
`~/.openinterpreter/config.toml` or `.openinterpreter/config.toml`; built-in
providers use their documented provider variables. The key value should come
from environment or the host credential store, not from repository config.

To scope the selected provider key to the ALK harness process, put it in a
private operator env file and explicitly allow that variable for the run:

```bash
python tools/live_hosts/openinterpreter_harness.py \
  --mode preflight \
  --interpreter-model <model-id> \
  --host-env-file ~/.config/alk/hosts/openinterpreter.env \
  --host-env-allow PROVIDER_API_KEY \
  --budget-mode subscription \
  --max-invocations 14 \
  --max-billable-tokens 1000 \
  --allow-live \
  --report work/release-1-18/evidence/preflight/openinterpreter-preflight-report.json
```

Replace `PROVIDER_API_KEY` with the selected provider's configured or
documented env-key name.

Progress bridge: OpenInterpreter documents `MANUAL` support. Provider
credentials and telemetry stay outside ALK core.

## Pi

```bash
pi --version
agent-lifecycle adapter install-plan --descriptor adapters/pi/adapter.descriptor.json
```

Pi has host-specific `VERIFIED` support for Pi `0.83.0` on the tested
host-local provider/model binding. The selected provider's credential must be
visible to the `pi` process before a local live rerun can start. Use Pi's own
provider documentation or config to choose the env-key name; the host
configuration remains the source of that name.

To scope that key to the ALK harness process, use a private operator env file
and explicitly allow the selected provider variable:

```bash
python tools/live_hosts/pi_harness.py \
  --mode preflight \
  --pi-provider <provider> \
  --pi-model <model-id> \
  --host-env-file ~/.config/alk/hosts/pi.env \
  --host-env-allow <PROVIDER_API_KEY_NAME> \
  --budget-mode subscription \
  --max-invocations 14 \
  --max-billable-tokens <token-cap> \
  --allow-live \
  --report work/<release>/evidence/preflight/pi-preflight-report.json
```

The verified Pi evidence covers the tested host-local provider/model binding;
ACP, public-directory and production-promotion scope are tracked separately.

Progress bridge: Pi documents `MANUAL` support. Provider credentials and
telemetry stay outside ALK core.

## Support qualification

Installation and support qualification are separate steps. A host-specific
`VERIFIED` claim uses accepted live host conformance, live usage calibration,
tracked redacted evidence and final lifecycle proof for the exact host range.
