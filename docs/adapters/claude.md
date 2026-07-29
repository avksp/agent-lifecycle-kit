# Claude Code adapter

The Claude Code projection packages the shared lifecycle skills, root
`.claude-plugin/plugin.json`, and root `.claude-plugin/marketplace.json`.
`adapters/claude/` remains an offline conformance projection.

Install from the tagged source marketplace:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

Run `/reload-plugins` after installation in an interactive session. The adapter
remains `EXPERIMENTAL` until live Claude Code install and lifecycle conformance
evidence is published in the support matrix.

## Event bridge

The Claude projection maps host progress into neutral `agent-adapter-event.v1`
records. A completed task stream must include session start, task launch,
command completion, write summary, optional usage reporting when the host
provides it, and one terminal task event. Blocked runs must end with
`task.blocked` instead of prose-only success.

Validate captured event files before accepting adapter evidence:

```bash
agent-lifecycle adapter event-check \
  --event events/001-session-started.json \
  --event events/002-task-launched.json \
  --event events/003-command-completed.json \
  --event events/004-writes-summarized.json \
  --event events/005-task-completed.json
```

The bridge is intentionally host-neutral: Claude-specific session identifiers
stay inside event `payload` or redacted host receipts, while lifecycle state,
task identity, sequence, status and terminal semantics are validated by core.
