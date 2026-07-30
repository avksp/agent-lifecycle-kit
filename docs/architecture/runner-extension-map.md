# Runner Extension Map

The runner is intentionally narrow. It records transition state and resource
counters, then delegates actual lifecycle mutations to existing workflow
commands and future adapters.

## Worktree Preservation

Planned integration point:

- transition history can reference worktree or attempt receipts by evidence id;
- runner state does not store platform paths as authority;
- cleanup remains conservative and operator-approved.

The runner must not delete worktrees or rewrite user files directly.

## Host Event Injection

Planned integration point:

- adapter events can be attached to transition evidence;
- event records stay in the neutral `agent-adapter-event.v1` shape;
- runner decisions consume validated event summaries, not provider-specific
  event names.

The runner must not depend on one host's hook or stream format.

## Review Quality

The runner may route remediation from structured review results once those
contracts exist. Until then, it records the selected transition and evidence ids
only. Full review artifacts remain authoritative for larger-model review and
final audit.

## Non-Goals

- no background daemon;
- no task scheduler product UI;
- no provider-specific execution loop in core;
- no database or long-running server dependency.
