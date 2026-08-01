# Optional quality packs

Optional quality packs describe extra checks that can be enabled by an
operator without changing the normal lifecycle path. `agent-optional-quality-pack.v1`
requires the pack to be disabled by default, opt-in, resource capped and free of
provider-specific core dependencies.

Each declared command must list its input schemas, expected evidence and
resource caps. The default command footprint must stay zero so routine workflow
commands remain lightweight.

Adaptive lifecycle policy can use a pack or task profile as required evidence
only after it is explicitly selected. Required evidence can raise the quality
floor, but packs remain disabled by default and resource capped.

`agent-optional-quality-pack-validation.v1` fails closed when a pack is enabled
by default, changes canonical lifecycle commands, lacks resource caps or claims
promotion. `agent-behavior-check-fixture.v1` and `agent-behavior-check-run.v1`
measure concrete lifecycle outcomes such as false completion, stale state,
over-budget retry, missing event capture and blocked external action.

```bash
agent-lifecycle quality pack-check --manifest <quality-pack.json>
agent-lifecycle quality behavior-check --manifest <quality-pack.json> --fixture <behavior-fixture.json>
agent-lifecycle quality template-list
agent-lifecycle quality template-check --template-id bugfix
agent-lifecycle quality bug-recipe-list
agent-lifecycle quality bug-recipe-check --recipe-id reproduction
```

When no manifest is provided, the CLI validates the built-in optional pack.
Negative fixtures pass the behavior check only when the expected failure or
block is detected.

Task templates are draft-only planning aids. They are disabled by default,
require explicit selection and keep review/freeze gates intact. Template checks
validate the markdown files under `templates/tasks/` for draft-only markers,
absence of runtime defaults and bounded size.

Bug Forensics recipes are optional recipe metadata for common defect-repair
stages. They reuse the existing reproduction, fingerprint, hypothesis,
regression-proof, fix-impact, cross-check and gate receipts; they do not create
a competing bug-fix schema chain.
