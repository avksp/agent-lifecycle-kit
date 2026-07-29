# Claude Code adapter

The Claude Code projection packages the shared lifecycle skills, root
`.claude-plugin/plugin.json`, and root `.claude-plugin/marketplace.json`.
`adapters/claude/` is `VERIFIED` for the tested Claude Code 2.1.220 host range
recorded in `adapters/claude/adapter.descriptor.json`.

Install from the tagged source marketplace:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

Run `/reload-plugins` after installation in an interactive session. The
verified claim is local and host-specific: it is backed by release-0-5 live conformance,
live calibration, and full ALK lifecycle evidence in
the support matrix. It does not claim official Claude directory approval,
universal host support, or a broader production-promotion platform matrix pass.

## Live evidence

Current verified range:

- Claude Code 2.1.220.
- Source revision `6bb3b58ee01d028fe21cef209c284efc79e55ceb`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/claude-code-0.5.0.md`.
- Host conformance:
  `tasks/release-0-5/evidence/live-host-conformance-claude-code.json`.
- Live calibration:
  `tasks/release-0-5/evidence/live-calibration-verification-claude-code.json`.
- Full lifecycle proof:
  `tasks/release-0-5/evidence/0.5.1-claude-live-promotion/full-lifecycle/final/final-proof.json`.

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
