# Using ALK with an adapter

ALK can be used from inside a supported host CLI or as a separate command in
the project terminal. These routes can be combined, but they do not provide the
same guarantees.

For the practical limits of several agents, custom plan stages, host model
settings, prompts, timeouts and retries, see [Workflow customization and
execution controls](../reference/workflow-customization.md).

## Inside the host CLI

A host-integrated plugin or skill teaches the coding agent how to use the ALK
lifecycle. After installing it, open the target project in the host and give an
explicit instruction such as:

```text
Use the agent-workflow-orchestrator skill for this task.
Keep the ALK plan, state, reviews, evidence and final proof in the project.
Task: <describe the task or name the Markdown file to read>
```

The host still owns model selection, tool calls, approvals and process
execution. Installing or mentioning a skill does not prove that the lifecycle
ran. A managed claim requires ALK state transitions and accepted receipts.

## From the project terminal

The same task can enter ALK from the project terminal:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md
agent-lifecycle start --adapter <adapter-id> --text "Review the cache design"
```

Replace `<adapter-id>` with an id from the linked table below. Raw text or
Markdown creates a review-required draft receipt. Add an explicit, qualified
`--launch` route when the operator wants one bound host process.

This route is preferable for scripts, reproducible evidence, CI preparation
and hosts without a shipped plugin. An integrated host may call the same
command itself; the resulting receipts, rather than the plugin installation,
are the lifecycle proof.

## Bundled adapter routes

| Adapter | Adapter id | Shipped inside-host route |
| --- | --- | --- |
| [Codex](codex.md) | `codex` | Install the Codex plugin, restart the session and request `agent-workflow-orchestrator`. |
| [Claude Code](claude.md) | `claude` | Install the Claude plugin, run `/reload-plugins` and request `agent-workflow-orchestrator`. |
| [Cursor](cursor.md) | `cursor` | Link the Cursor plugin checkout, reload Cursor and request `agent-workflow-orchestrator`. |
| [OpenCode](opencode.md) | `opencode` | Copy the shared skills and JS projection into the configured OpenCode directories, then request the skill. |
| [Hermes](hermes.md) | `hermes` | Install the tagged skill and run `/agent-lifecycle-kit:agent-workflow-orchestrator`. |
| [Gemini CLI](gemini-cli.md) | `gemini-cli` | Configure the tagged shared skills through the host skill directory or use the terminal route. |
| [Kimi Code](kimi-code.md) | `kimi-code` | Select the host skill directory, add the tagged shared skills and use the terminal route when preferred. |
| [Pi](pi.md) | `pi` | Use the host's AGENTS/Agent Skills configuration to expose the tagged skill, or use the terminal route. |
| [Goose](goose.md) | `goose` | Use the terminal route or expose the shared ALK commands through an operator-owned wrapper. |
| [Grok Build](grok-build.md) | `grok-build` | Use the terminal route or expose the shared ALK commands through an operator-owned wrapper. |
| [OpenInterpreter](openinterpreter.md) | `openinterpreter` | Use the terminal route or expose the shared ALK commands through an operator-owned wrapper. |
| [Qwen Code](qwen-code.md) | `qwen-code` | Use the terminal route or configure a separately verified host integration. |

Run `agent-lifecycle adapter install-plan --descriptor
adapters/<adapter-id>/adapter.descriptor.json` before changing host files. The
plan is a preview: it does not execute installation commands.

## Command route versus host route

| Property | Inside the host CLI | `agent-lifecycle` command |
| --- | --- | --- |
| Starts a model | The host does so under its own configuration. | A qualified `--launch` route starts one bound host process. |
| Selects a model/provider | The host or operator. | ALK records the neutral route and accepted host evidence. |
| Reads the task | The host reads the prompt or referenced file. | ALK reads `--text` or `--file` and creates a bounded receipt. |
| Proves the lifecycle | The host session records accepted ALK artifacts. | Required state transitions, reviews, audits and receipts form the proof. |
| Best fit | Interactive work in a host that can load ALK skills. | Automation, repeatability, evidence and hosts without a plugin. |

## Direct external process launch

`--launch` is the explicit host-process route. Planning launch uses
`PLANNING_ONLY_QUALIFIED`; frozen implementation launch uses a complete frozen
request, risk bindings, an exact-version local profile and a matching preflight
receipt.

Use the support stated in [Qualified frozen-task host
launch](../reference/qualified-host-launch.md) when accepted launch evidence is
required. The guide describes the profile, preflight and receipt sequence.

See also [Adapter installation](install.md), [Adapter support
matrix](support-matrix.md) and [Planning-only adapter
launch](../reference/planning-only-launch.md).
