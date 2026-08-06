# Runner extension map

The runner is intentionally narrow. It records transition state and resource
counters, then delegates actual lifecycle mutations to existing workflow
commands and adapter-session bridges.

## Worktree preservation

Current integration:

- attempt transitions can validate a worktree isolation receipt through
  `validate_attempt_isolation_receipt`;
- transition history stores evidence ids and isolation receipt digests instead
  of using platform paths as authority;
- attempt snapshots and sandbox receipts live beside the runner, while cleanup
  remains conservative and operator-approved.

The runner must not delete worktrees or rewrite user files directly.

## Host event injection

Current integration boundary:

- adapter events can be attached to transition evidence by evidence id;
- event records stay in the neutral `agent-adapter-event.v1` shape;
- runner decisions consume validated event summaries and do not parse
  provider-specific event names or host stream formats.

The runner must not depend on one host's hook or stream format.

## Review quality

Structured review and multi-review contracts now exist under
`review_mesh/*`. The runner still records the selected transition and evidence
ids only. Workflow adoption, implementation audit and finalization can enforce
review-mesh quorum through `workflow/review_mesh_gate.py` when the frozen plan
opts in. Full review artifacts remain authoritative for larger-model review and
final audit.

## Non-goals

- no background daemon;
- no task scheduler product UI;
- no provider-specific execution loop in core;
- no database or long-running server dependency.
