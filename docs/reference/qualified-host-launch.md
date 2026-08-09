# Qualified host launch

ALK ships version-bound local launch profiles for three external CLIs. This is
an opt-in bridge for a frozen ALK task, not a provider broker and not a blanket
native-launch claim.

| Adapter | Qualified CLI version | Generated executable |
| --- | --- | --- |
| Codex | `0.147.0` | `codex` |
| Claude Code | `2.1.226` | `claude` |
| OpenCode | `1.18.15` | `opencode` |

The adapter descriptors remain `managedLaunch.status: WRAPPER_ONLY`. The
qualification applies only to the exact local profile and installed version.

## Create the local profile

Run the command from the target project. Point `--repository-root` at the ALK
source or plugin checkout that contains the adapter profile:

```bash
agent-lifecycle adapter launch-profile \
  --adapter codex \
  --repository-root /path/to/agent-lifecycle-kit \
  --out .alk/host-launch/codex.json
```

Replace `codex` with `claude` or `opencode` for another qualified adapter. The
output is restricted to `.alk/host-launch/<name>.json`; ALK rejects absolute,
nested, traversal and symlink paths.

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
See [Local host launch](local-host-launch.md), [Managed adapter
sessions](managed-adapter-sessions.md) and the [Adapter support
matrix](../adapters/support-matrix.md).
