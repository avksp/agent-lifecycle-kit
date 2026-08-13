# Frozen-task launch through a verified profile

ALK provides an opt-in route for launching a frozen task through a verified
external-tool profile. The profile binds the exact command version, process
parameters, profile digest and preflight receipt to the task and lifecycle
evidence. Provider and model selection stay in the host configuration.

In technical schemas and receipts, this state is called `qualified`. For
operators, it means that the profile has been verified; it is not a separate
provider or model selection.

This page covers implementation of an already reviewed frozen task. Planning
uses the separate [Planning-only adapter launch](planning-only-launch.md)
workflow.

| Adapter | Verified CLI version | Generated executable |
| --- | --- | --- |
| [Codex](../adapters/codex.md) | `0.147.0` | `codex` |
| [Claude Code](../adapters/claude.md) | `2.1.226` | `claude` |
| [OpenCode](../adapters/opencode.md) | `1.18.15` | `opencode` |

The adapter descriptors remain `managedLaunch.status: WRAPPER_ONLY`. The
verification applies only to the exact local profile and installed version.

## Verified profiles

All twelve bundled adapters have an exact-version local profile declaration,
so `adapter launch-profile`, profile inspection and bounded version preflight
can be exercised for each one. That declaration is broader than verified
frozen-task execution.

The three adapters above have dedicated frozen-task continuation profiles,
launch harnesses and usage normalizers for this route. The remaining adapter
profiles are listed below with their current planning status:

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
`productionPromotionClaimed` are recorded as `false`. A successful `--version`
preflight confirms profile and version identity; accepted implementation
evidence uses the complete verification sequence for the selected adapter.

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

Use the verified profile only with the complete frozen `implement` request:

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

The shipped argv contains the frozen task binding and the approved process
arguments. It instructs the CLI to continue the already frozen ALK task in the
current repository. ALK still verifies the plan lock, task lineage, operation,
source revision and risk profile immediately before process creation.

## Usage and support boundary

The three parsers normalize bounded JSONL usage artifacts. Their current
descriptor status is `FIXTURE_ONLY`; S1/S2 usage acceptance uses a separate
host-attested usage receipt.

The profile covers process identity, task binding and lifecycle evidence. Login,
account selection, provider choice, native configuration and native conversation
resume remain host responsibilities. See [Using ALK with an adapter](../adapters/usage-modes.md), [Local host
launch](local-host-launch.md), [Managed adapter
sessions](managed-adapter-sessions.md) and the [Adapter support
matrix](../adapters/support-matrix.md).
