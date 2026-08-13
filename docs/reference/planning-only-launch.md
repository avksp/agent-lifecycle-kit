# Planning-only adapter launch

ALK can accept task text or Markdown through one public command and, when an
exact-version adapter profile is verified, start one external CLI in a
planning-only process:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode plan \
  --file task.md \
  --launch
```

Without `--launch`, the same command performs local draft intake and does not
start a host process. Raw input in `--mode implement` is always rejected.

## Current support truth

Planning launch is a separate claim from the adapter support level and from
frozen-task launch through a verified profile.

| Adapter | Exact profile version | Profile status | Planning launch status |
| --- | --- | --- | --- |
| Codex | `0.147.0` | `CANDIDATE` | `PLANNING_ONLY_UNSUPPORTED` until live containment evidence passes |
| Claude Code | `2.1.226` | `CANDIDATE` | `PLANNING_ONLY_UNSUPPORTED` until live containment evidence passes |
| OpenCode | `1.18.15` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: no verified native read-only profile |
| Cursor Agent | `2026.07.23` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: bounded stdin result transport is not verified |
| Gemini CLI | `0.46.0` | `CANDIDATE` | `PLANNING_ONLY_UNSUPPORTED` until live containment evidence passes |
| Goose | `1.45.0` | `CANDIDATE` | `PLANNING_ONLY_UNSUPPORTED` until live containment evidence passes |
| Grok Build | `0.2.118` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: bounded stdin result transport is not verified |
| Hermes Agent | `0.19.0` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: one-shot tool denial is not verified |
| Kimi Code | `0.30.0` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: bounded stdin result transport is not verified |
| OpenInterpreter | `0.0.34` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: no reliable native read-only profile is exposed |
| Pi | `0.83.0` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: bounded stdin result transport is not verified |
| Qwen Code | `0.21.8` | `UNSUPPORTED` | `PLANNING_ONLY_UNSUPPORTED`: native read-only or tool denial is not verified |

The adapter support level `VERIFIED` and managed-session support `WRAPPER_ONLY`
do not promote this column. A structurally valid profile or successful version probe
also does not promote it. Until the profile carries exact-version
`PLANNING_ONLY_QUALIFIED` evidence, `--launch` fails closed before planning can
claim support.

## Prepare and inspect a candidate

All bundled adapters have exact-version profile generators. Generating and
inspecting a profile does not qualify it:

```bash
agent-lifecycle adapter launch-profile \
  --adapter codex \
  --repository-root /path/to/agent-lifecycle-kit \
  --out .alk/host-launch/codex.json

agent-lifecycle host-launch inspect \
  --profile .alk/host-launch/codex.json

agent-lifecycle host-launch preflight \
  --profile .alk/host-launch/codex.json
```

Replace `codex` with any adapter id from the table. The profile and its
preflight receipt stay below ignored `.alk/host-launch/`. Preflight verifies
the executable version with no model call; it is necessary but not sufficient
for planning qualification. An `UNSUPPORTED` profile remains blocked even
after a successful version probe. A `CANDIDATE` remains blocked until an
operator-approved live harness proves the exact version and containment
boundary and the shipped evidence is independently accepted.

If the default profile is missing, `start --launch` returns the exact profile
and preflight commands in its blockers. It does not create or trust a profile
implicitly.

## Security and lifecycle boundary

The verified planning route:

- passes bounded task data through standard input, never argv;
- uses an exact environment allowlist and `shell=False`;
- permits at most one bounded host process;
- requires the native host's read-only or tool-denial controls;
- compares the authoritative Git identity before and after the process;
- stores only task and result digests in `agent-planning-session-state.v1`
  under `.alk/planning-sessions`;
- returns `REVIEW_REQUIRED` or `BLOCKED` with
  `implementationAuthorized: false`.

The outer `agent-lifecycle-start-receipt.v1` keeps its stable
`DRAFT_PLAN_REVIEW` action and zero-model-call facade invariant. The nested
`agent-planning-launch-receipt.v1` records whether the host process and model
call actually started through `modelCallsStarted`.

Task content and host output remain untrusted data. They cannot approve tools,
freeze a plan, grant implementation authority or replace independent review.
ALK never resets operator changes when the before/after identity differs.

## Resume and handoff

The receipt contains an ALK planning session id. Resume reads digest-only
state and never reconnects to a native host conversation:

```bash
agent-lifecycle start --adapter codex --resume <planning-session-id>
```

A successful planning result stops at review. Implementation requires a
separately reviewed `FROZEN` manifest, matching lock, compiled task identity,
risk profile and a new verified `managedTask` process. See [Frozen-task launch
through a verified profile](qualified-host-launch.md) for that distinct route and [Managed adapter
sessions](managed-adapter-sessions.md) for the lower-level session commands.
