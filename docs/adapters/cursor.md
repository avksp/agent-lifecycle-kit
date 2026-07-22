# Cursor adapter

The Cursor projection packages shared lifecycle skills, root
`.cursor-plugin/plugin.json`, and root `.cursor-plugin/marketplace.json`.
`adapters/cursor/` remains an offline conformance projection.

The lifecycle core remains outside Cursor-specific prompt text. Cursor-specific
integration should only translate invocation, discovery and approval surfaces.

For local validation before public submission, symlink the repository into
`~/.cursor/plugins/local/agent-lifecycle-kit` and reload Cursor. Public
Marketplace publication requires submitting the public repository through
Cursor's review flow. The adapter remains `EXPERIMENTAL` until live Cursor
install and lifecycle conformance evidence is published in the support matrix.
