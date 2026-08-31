# Validation ladder

The validation ladder selects the smallest allowed feedback set for a changed
file set while preserving a complete release gate. Selection is deterministic,
read-only and command-free: ALK returns check IDs but does not execute their
command strings.

## Frozen inputs

An opted-in plan declares both optional fields under `validation`:

- `checkCatalog`: a closed `agent-validation-check-catalog.v1` object whose
  records bind a stable check ID to the digest of one exact
  `validation.commands` string;
- `validationLadderProfile`: a path and digest for a closed
  `agent-validation-ladder-profile.v1` mapping literal repository prefixes to
  `TASK_FAST`, `TASK_ACCEPTANCE` or `RELEASE_FULL` check IDs.

The fields are all-or-none and are covered by the plan lock. Profiles contain
no commands. Glob paths, unknown check IDs, contradictory duplicate mappings,
unreadable or stale profile bytes, and stale plan/lock lineage block selection.

## Select checks

```bash
agent-lifecycle workflow validation-select \
  --state <run.state.json> \
  --task <task-id> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --snapshot <task-change-set.json> \
  --out <validation-selection.json>
```

The `agent-validation-selection.v1` result contains the selected level and
check IDs with `commandsExecuted: false` and `stateWritten: false`. A host or
operator resolves the IDs against the frozen command catalog, runs those exact
commands, and records ordinary evidence. Selection never accepts a task.

## Conservative floor

Plans without the optional profile select `RELEASE_FULL`. A valid profile with
no matching mapping also selects `RELEASE_FULL`. Changes to protected release,
security, architecture, policy, contracts, documentation or publication paths
always select `RELEASE_FULL`; profile additions may widen but cannot reduce
that built-in floor.

For an opted-in plan, finalization requires a fresh
`agent-release-full-validation-receipt.v1` through
`workflow finalize --release-full-receipt`. Its passed check IDs must exactly
equal the required full set and its plan, lock, source, current-tree and catalog
lineage must match. Focused receipts cannot substitute for it, and the existing
post-merge publication gates remain separate.

