# OpenCode adapter

The OpenCode projection packages shared lifecycle skills, root `opencode.json`,
and an OpenCode JS adapter under `adapters/opencode/`.

OpenCode-specific code must not reimplement lifecycle planning, freeze,
workflow, review or final-audit semantics.

OpenCode loads plugins and skills separately. Copy `skills/*` into
`.opencode/skills/` or `~/.config/opencode/skills/`, and copy
`adapters/opencode/plugins/agent-lifecycle-kit.js` into the matching
`.opencode/plugins/` location. The adapter remains `EXPERIMENTAL` until live
OpenCode conformance evidence is published in the support matrix.
