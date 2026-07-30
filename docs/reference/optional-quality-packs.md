# Optional Quality Packs

Optional quality packs describe extra checks that can be enabled by an
operator without changing the normal lifecycle path. `agent-optional-quality-pack.v1`
requires the pack to be disabled by default, opt-in, resource capped and free of
provider-specific core dependencies.

Each declared command must list its input schemas, expected evidence and
resource caps. The default command footprint must stay zero so routine workflow
commands remain lightweight.

`agent-optional-quality-pack-validation.v1` fails closed when a pack is enabled
by default, changes canonical lifecycle commands, lacks resource caps or claims
promotion. `agent-behavior-check-fixture.v1` and `agent-behavior-check-run.v1`
measure concrete lifecycle outcomes such as false completion, stale state,
over-budget retry, missing event capture and blocked external action.

```bash
agent-lifecycle quality pack-check --manifest <quality-pack.json>
agent-lifecycle quality behavior-check --manifest <quality-pack.json> --fixture <behavior-fixture.json>
```

When no manifest is provided, the CLI validates the built-in optional pack.
Negative fixtures pass the behavior check only when the expected failure or
block is detected.
