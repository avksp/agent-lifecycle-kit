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
