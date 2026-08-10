# Planning-only adapter launch

ALK can accept task text or Markdown through one public command and, when an
exact-version adapter profile is qualified, start one external CLI in a
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

Planning launch is a separate claim from adapter maturity and from qualified
launch of a frozen implementation task.

| Adapter | Exact candidate version | Planning launch status |
| --- | --- | --- |
| Codex | `0.147.0` | `PLANNING_ONLY_UNSUPPORTED` until live containment evidence passes |
| Claude Code | `2.1.226` | `PLANNING_ONLY_UNSUPPORTED` until live containment evidence passes |
| OpenCode | `1.18.15` | `PLANNING_ONLY_UNSUPPORTED` until a safe planning profile and live evidence pass |
| Cursor, Gemini CLI, Goose, Grok Build, Hermes, Kimi Code, OpenInterpreter, Pi, Qwen Code | Not declared in this contract | Unsupported for planning launch |

`VERIFIED` adapter maturity and `WRAPPER_ONLY` managed-session support do not
promote this column. A structurally valid profile or successful version probe
also does not promote it. Until the profile carries exact-version
`PLANNING_ONLY_QUALIFIED` evidence, `--launch` fails closed before planning can
claim support.

## Prepare and inspect a candidate

Codex, Claude Code and OpenCode have candidate profile generators:

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

Replace `codex` with `claude` or `opencode` as needed. The profile and its
preflight receipt stay below ignored `.alk/host-launch/`. Preflight verifies
the executable version with no model call; it is necessary but not sufficient
for planning qualification.

If the default profile is missing, `start --launch` returns the exact profile
and preflight commands in its blockers. It does not create or trust a profile
implicitly.

## Security and lifecycle boundary

The qualified planning route:

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
risk profile and a new qualified `managedTask` process. See [Qualified host
launch](qualified-host-launch.md) for that distinct route and [Managed adapter
sessions](managed-adapter-sessions.md) for the lower-level session commands.
