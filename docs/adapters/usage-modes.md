# Using ALK with an adapter

ALK can be used from inside a supported host CLI or as a separate command in
the project terminal. These routes can be combined, but they do not provide the
same guarantees.

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

The same task can enter ALK without starting the host CLI:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md
agent-lifecycle start --adapter <adapter-id> --text "Review the cache design"
```

Replace `<adapter-id>` with an id from the linked table below. Raw text or
Markdown creates a review-required draft receipt. The command does not call a
model or start the external CLI unless the operator also supplies an explicit,
qualified `--launch` route.

In other words, the normal command route does not start the external CLI.

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
| [Gemini CLI](gemini-cli.md) | `gemini-cli` | The host can discover skills, but this adapter does not modify its skill directory; configure the tagged shared skills explicitly or use the terminal route. |
| [Kimi Code](kimi-code.md) | `kimi-code` | The host exposes skill-directory selection, but this adapter does not install skills; configure the tagged shared skills explicitly or use the terminal route. |
| [Pi](pi.md) | `pi` | Use the host's AGENTS/Agent Skills configuration to expose the tagged skill, or use the terminal route. |
| [Goose](goose.md) | `goose` | No inside-host ALK plugin is shipped; use the terminal route or an operator-owned wrapper. |
| [Grok Build](grok-build.md) | `grok-build` | No inside-host ALK plugin is shipped; use the terminal route or an operator-owned wrapper. |
| [OpenInterpreter](openinterpreter.md) | `openinterpreter` | No inside-host ALK plugin is shipped; use the terminal route or an operator-owned wrapper. |
| [Qwen Code](qwen-code.md) | `qwen-code` | No inside-host ALK installation route is claimed by the bundled projection; use the terminal route or a separately verified host configuration. |

Run `agent-lifecycle adapter install-plan --descriptor
adapters/<adapter-id>/adapter.descriptor.json` before changing host files. The
plan is a preview: it does not execute installation commands.

## Command route versus host route

| Property | Inside the host CLI | `agent-lifecycle` command |
| --- | --- | --- |
| Starts a model | The host may do so under its own configuration. | No, unless an explicit qualified `--launch` route is requested. |
| Selects a model/provider | The host or operator. | Never; ALK records only neutral routing and accepted host evidence. |
| Reads the task | The host reads the prompt or referenced file. | ALK reads `--text` or `--file` and creates a bounded receipt. |
| Proves the lifecycle | Not by plugin or skill installation. | Only when required state transitions, reviews, audits and receipts are accepted. |
| Best fit | Interactive work in a host that can load ALK skills. | Automation, repeatability, evidence and hosts without a plugin. |

## Direct external process launch

`--launch` is a third, narrower route, not a synonym for using ALK inside a
host. Planning launch requires `PLANNING_ONLY_QUALIFIED`; all bundled adapters
currently fail closed for that status. Frozen implementation launch requires a
complete frozen request, risk bindings, an exact-version local profile and a
matching preflight receipt.

Only the support stated in [Qualified frozen-task host
launch](../reference/qualified-host-launch.md) may be treated as accepted
launch evidence. The presence of a profile declaration or a successful
`--version` preflight is not enough.

See also [Adapter installation](install.md), [Adapter support
matrix](support-matrix.md) and [Planning-only adapter
launch](../reference/planning-only-launch.md).
