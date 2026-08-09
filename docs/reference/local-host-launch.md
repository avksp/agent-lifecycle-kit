# Local host launch

Local host launch is an advanced, explicit way to start one external command
after ALK has accepted a fully bound frozen run. It does not change adapter
maturity, install host credentials, inject task text, or turn a
`WRAPPER_ONLY` adapter into a publicly supported native launcher.

The local profile is operator-owned and must be stored below
`.alk/host-launch/`. The complete `.alk/` tree is ignored by Git.
Its public schema id is `agent-local-host-launch-profile.v1`.

## Create a local profile

For Codex `0.147.0`, Claude Code `2.1.226` and OpenCode `1.18.15`, prefer the
shipped version-bound builder described in [Qualified host
launch](qualified-host-launch.md). The manual format below remains available
for an operator-owned wrapper and does not carry a host qualification claim.

Create `.alk/host-launch/codex.json`:

```json
{
  "schemaVersion": "agent-local-host-launch-profile.v1",
  "status": "LOCAL_OPT_IN",
  "adapterId": "codex",
  "executable": "codex",
  "argvTemplate": [],
  "versionProbeArgs": ["--version"],
  "env": {
    "allow": ["HOME", "PATH"],
    "allowPatterns": [],
    "projectPolicyAllowed": false
  },
  "timeoutSeconds": 30,
  "shell": false,
  "writesNativeConfig": false,
  "promptInjectionDefault": false,
  "publicSupportClaimed": false,
  "productionPromotionClaimed": false
}
```

`executable` is one exact process token, not a command string. Shell
executables, relative path traversal, environment wildcards, partial
placeholder interpolation and unknown placeholders are rejected.

`versionProbeArgs` is restricted to exactly `--version`, `-V`, or `version`.
A bare executable name also requires `PATH` in the exact environment allowlist.
This keeps `preflight` a version probe instead of a general command runner.

`argvTemplate` accepts literal tokens and these whole-token placeholders:

- `{adapter_id}`;
- `{state_path}`, `{manifest_path}` and `{lock_path}`;
- `{task_id}`, `{operation_id}` and `{source_revision}`;
- `{risk_profile_digest}`.

Raw task text is deliberately absent. A profile can start an installed host or
wrapper, but it cannot smuggle an unreviewed prompt into argv.

## Inspect and preflight

Inspection validates the path, schema and digest without starting a process:

```bash
agent-lifecycle host-launch inspect \
  --profile .alk/host-launch/codex.json
```

Preflight explicitly starts the configured executable once with only
`versionProbeArgs`. The probe is capped at 10 seconds even when the launch
timeout is larger:

```bash
agent-lifecycle host-launch preflight \
  --profile .alk/host-launch/codex.json
```

The receipt records `processCalls: 1`, the profile digest, exit status and
redacted output. Missing executables, non-zero exits and timeouts return a
structured failure.

For a shipped qualified profile, preflight also writes
`agent-host-launch-qualification-receipt.v1`. A later managed launch requires
that receipt to match the exact profile digest and CLI version.

## Launch a frozen run

First produce a complete `agent-adapter-task-run-request.v1` whose `state`,
`manifest`, `lock`, `task`, `operationId`, `expectedRevision` and
`sourceRevision` identify one frozen ALK task. For S1/S2, provide a valid
host-local model profile so ALK can derive resource caps and usage requirements.

```bash
agent-lifecycle start \
  --adapter codex \
  --mode implement \
  --file work/my-run/adapter-run-request.json \
  --risk auto \
  --host-model-profile profiles/hosts/codex-live-profile.v1.json \
  --launch \
  --host-launch-profile .alk/host-launch/codex.json
```

Immediately before process creation ALK verifies the frozen manifest and lock,
workflow lineage, task identity, derived risk profile, profile adapter and
explicit `--launch` flag. Only `launch_from_local_profile` reaches the secure
process runner.

The foundation does not inject task text or attach to a previous native host
conversation. A host-specific wrapper may use the frozen identity placeholders
to find its own reviewed input. Public host-specific launch qualification is a
separate evidence step.

## Fail-closed boundaries

- `start` with raw text, Markdown, research, plan or review mode never launches.
- `--launch` and `--host-launch-profile` must be supplied together.
- `host-launch inspect` starts zero processes.
- `host-launch preflight` starts at most one bounded version probe.
- `adapter session start --launch` remains blocked.
- `launch_from_descriptor` remains blocked even for a custom `SUPPORTED`
  descriptor.
- Environment values are selected only by exact names and are never written to
  receipts.
- Process output, argv paths and startup errors use shared receipt redaction.

See [Managed adapter sessions](managed-adapter-sessions.md), [Risk-aware
execution](risk-aware-execution.md) and the [Adapter support
matrix](../adapters/support-matrix.md).
