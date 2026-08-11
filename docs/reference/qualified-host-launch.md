# Qualified frozen-task host launch

ALK documents the frozen-task launch bridge for three external CLIs. This is
an opt-in bridge for a frozen ALK task, not a provider broker and not a blanket
native-launch claim for every adapter.

This page covers implementation of an already reviewed frozen task. It does
not qualify raw task planning. That separate fail-closed contract is described
in [Planning-only adapter launch](planning-only-launch.md).

| Adapter | Qualified CLI version | Generated executable |
| --- | --- | --- |
| [Codex](../adapters/codex.md) | `0.147.0` | `codex` |
| [Claude Code](../adapters/claude.md) | `2.1.226` | `claude` |
| [OpenCode](../adapters/opencode.md) | `1.18.15` | `opencode` |

The adapter descriptors remain `managedLaunch.status: WRAPPER_ONLY`. The
qualification applies only to the exact local profile and installed version.

## Why this table has three adapters

All twelve bundled adapters have an exact-version local profile declaration,
so `adapter launch-profile`, profile inspection and bounded version preflight
can be exercised for each one. That declaration is broader than qualified
frozen-task execution.

The three adapters above also have the dedicated frozen-task continuation
profiles, launch harnesses and usage normalizers introduced for this route.
The other nine declarations were added to make planning qualification explicit
and fail closed. They do not make a public managed-task launch claim:

| Adapter | Declared version | Executable | Current boundary |
| --- | --- | --- | --- |
| [Cursor](../adapters/cursor.md) | `2026.07.23` | `cursor-agent` | Exact-version declaration; planning profile is `UNSUPPORTED`. |
| [Gemini CLI](../adapters/gemini-cli.md) | `0.46.0` | `gemini` | Static planning candidate without accepted containment evidence. |
| [Goose](../adapters/goose.md) | `1.45.0` | `goose` | Static planning candidate without accepted containment evidence. |
| [Grok Build](../adapters/grok-build.md) | `0.2.118` | `agent` | Exact-version declaration; planning profile is `UNSUPPORTED`. |
| [Hermes](../adapters/hermes.md) | `0.19.0` | `hermes` | Exact-version declaration; planning profile is `UNSUPPORTED`. |
| [Kimi Code](../adapters/kimi-code.md) | `0.30.0` | `kimi` | Exact-version declaration; planning profile is `UNSUPPORTED`. |
| [OpenInterpreter](../adapters/openinterpreter.md) | `0.0.34` | `interpreter` | Version-only safe declaration; planning profile is `UNSUPPORTED`. |
| [Pi](../adapters/pi.md) | `0.83.0` | `pi` | Exact-version declaration; planning profile is `UNSUPPORTED`. |
| [Qwen Code](../adapters/qwen-code.md) | `0.21.8` | `qwen` | Exact-version declaration; planning profile is `UNSUPPORTED`. |

For every row, `qualifiedLaunch.publicSupportClaimed` and
`productionPromotionClaimed` remain `false`. A successful `--version`
preflight proves only profile/version identity. Do not use one of these nine
profiles as accepted implementation evidence unless a later adapter-specific
qualification explicitly promotes that route.

## Create the local profile

Run the command from the target project. Point `--repository-root` at the ALK
source or plugin checkout that contains the adapter profile:

```bash
agent-lifecycle adapter launch-profile \
  --adapter codex \
  --repository-root /path/to/agent-lifecycle-kit \
  --out .alk/host-launch/codex.json
```

Replace `codex` with `claude` or `opencode` for another documented frozen-task
adapter. Profile generation also accepts the other bundled adapter ids, but
their boundary is the one stated above. The output is restricted to
`.alk/host-launch/<name>.json`; ALK rejects absolute, nested, traversal and
symlink paths.

## Verify the installed CLI

Inspection starts no process:

```bash
agent-lifecycle host-launch inspect \
  --profile .alk/host-launch/codex.json
```

Preflight runs exactly one bounded `--version` process and writes a
digest-bound qualification receipt next to the profile:

```bash
agent-lifecycle host-launch preflight \
  --profile .alk/host-launch/codex.json
```

The receipt schema is `agent-host-launch-qualification-receipt.v1`.

The receipt must report the same adapter, profile digest and exact expected and
actual version. A missing receipt, changed profile, changed CLI version,
timeout or non-zero exit blocks the later managed launch before process
creation.

## Start the frozen task

Use the qualified profile only with the complete frozen `implement` request:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode implement \
  --file work/run/adapter-run-request.json \
  --risk auto \
  --host-model-profile profiles/hosts/codex-live-profile.v1.json \
  --launch \
  --host-launch-profile .alk/host-launch/codex.json
```

The shipped argv does not contain raw task text or unsafe automatic-approval
flags. It instructs the CLI to continue the already frozen ALK task in the
current repository. ALK still verifies the plan lock, task lineage, operation,
source revision and risk profile immediately before process creation.

## Usage and support boundary

The three parsers normalize bounded JSONL usage artifacts, but their current
descriptor status is `FIXTURE_ONLY` and `acceptedForS1S2: false`. Version
preflight does not prove model-token accounting. S1/S2 acceptance therefore
remains blocked until a separate host-attested usage receipt is available.

The profile does not log in, share accounts, choose a provider, change native
configuration, resume a native conversation or promote adapter maturity.
See [Using ALK with an adapter](../adapters/usage-modes.md), [Local host
launch](local-host-launch.md), [Managed adapter
sessions](managed-adapter-sessions.md) and the [Adapter support
matrix](../adapters/support-matrix.md).
