# Adapter install

Adapter setup is intentionally split into two steps:

1. Validate and inspect source metadata.
2. Apply host-local installation commands only after operator review.

Use the dry-run planner first:

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

The planner records `writesStarted: false`, `liveCallsStarted: false`, and
`maturityChangeClaimed: false`.

## Common checks

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json \
  --skip-host-commands
```

`adapter inspect` is a safe source and command-surface check. It is not live
host conformance.

## Publication channels

Install from immutable semantic-version refs by default. Root plugin manifests
and adapter-local plugin projections must declare the real semver in `version`.
Marketplace source refs use `source.ref: vX.Y.Z` when the host installs from a
repository tag.

A floating `last` channel, when supported by a host, is opt-in only and may
point to an accepted release commit as a source ref. It must not become the
default install path and must not replace semver inside `plugin.json`.

## Host-local secrets

Adapters that call a real model should receive credentials through the host's
normal mechanism: environment variables, the host credential store or an
operator-managed secret launcher. ALK does not store provider keys in tracked
config, descriptors, receipts or release evidence.

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

The harness passes only the allowed names to the child host process and records
only `agent-host-env-file-redacted.v1` metadata. `tools/release/validate_host_env_hygiene.py`
checks that the secret value is absent from reports and receipts.

This rule applies to every provider-flexible adapter. If the host can switch
providers or models, the selected provider remains responsible for the
credential name and source; ALK only receives the operator-approved variable
name for the current harness run.

## Managed lifecycle handoff

Hosts that want one deterministic lifecycle loop can call
`agent-lifecycle workflow run` before launching work. The command returns the
next action and fail-closed blockers, but it does not start a model, mutate
workflow state or write host secrets into receipts. Adapters remain responsible
for native launches, waits, cancellation and telemetry.

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

## Cursor

Files:

- `.cursor-plugin/plugin.json`
- `.cursor-plugin/marketplace.json`
- `adapters/cursor/*`
- `skills/`

Cursor remains `EXPERIMENTAL`. Local linking is useful for manual inspection,
but it is not promotion evidence:

```bash
ln -s <checkout> ~/.cursor/plugins/local/agent-lifecycle-kit
```

## OpenCode

Files:

- `opencode.json`
- `adapters/opencode/plugins/agent-lifecycle-kit.js`
- `skills/`

Operator flow depends on whether the user wants project-level or user-level
configuration. The dry-run install plan shows the exact source files to copy or
link. OpenCode is host-specific `VERIFIED` only for the tested range in the
support matrix.

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

Gemini CLI remains `EXPERIMENTAL` until accepted live conformance, usage
calibration, and lifecycle proof exist for a concrete host range.

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

Kimi Code remains `EXPERIMENTAL` until provider/model configuration, live
conformance, usage calibration, and lifecycle proof are accepted.

## Grok Build

```bash
grok --version
grok agent --help
agent-lifecycle adapter install-plan --descriptor adapters/grok-build/adapter.descriptor.json
```

Grok Build has host-specific `VERIFIED` support for Grok Build `0.2.117` on the
tested host-local provider/model binding. The ACP path remains probe-gated, and
a failed probe is recorded as fail-closed evidence.

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

## Pi

```bash
pi --version
agent-lifecycle adapter install-plan --descriptor adapters/pi/adapter.descriptor.json
```

Pi has host-specific `VERIFIED` support for Pi `0.83.0` on the tested
host-local provider/model binding. The selected provider's credential must be
visible to the `pi` process before a local live rerun can start. Use Pi's own
provider documentation or config to choose the env-key name; ALK does not
hardcode provider secret names.

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

The verified Pi claim does not claim ACP support, public directory approval or
production promotion.

## Promotion boundary

Installation is not a maturity change. A host-specific `VERIFIED` claim needs
accepted live host conformance, live usage calibration, tracked redacted
evidence, and final lifecycle proof for the exact host range.
