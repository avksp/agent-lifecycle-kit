# Adapter Install

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

## Common Checks

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

Qwen Code is host-specific `VERIFIED` only for the tested GLM 5.2 binding and
host range in the support matrix.

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

## Promotion Boundary

Installation is not a maturity change. A host-specific `VERIFIED` claim needs
accepted live host conformance, live usage calibration, tracked redacted
evidence, and final lifecycle proof for the exact host range.
