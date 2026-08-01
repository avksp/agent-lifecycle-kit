# Worktree isolation receipts

Worktree isolation receipts document that a task attempt ran in a bounded
attempt workspace and did not overwrite unrelated local changes. The core
records and validates receipts; it does not create, delete or rewrite
worktrees.

`agent-worktree-isolation-policy.v1` defines:

- a repository-relative worktree root;
- allowed write roots;
- whether failed attempts are preserved by default;
- whether cleanup requires operator authorization.

`agent-worktree-attempt-receipt.v1` binds the workflow lineage, task id,
attempt, baseline, changed files, cleanup decision and receipt digest.
Changed files must remain inside the task write scope. A failed attempt is
preserved unless an explicit operator authorization allows removal.

## Commands

```bash
agent-lifecycle worktree policy-check --policy <worktree-policy.json>
agent-lifecycle worktree receipt --state <run.state.json> --policy <worktree-policy.json> --task <task-id> --attempt <n> --worktree-path <relative-path> --baseline-ref <ref> --baseline-sha <sha> --changed-file <path> --reason "<reason>" --out <worktree-receipt.json>
agent-lifecycle worktree check --receipt <worktree-receipt.json> --state <run.state.json> --policy <worktree-policy.json>
```

`runner transition` attempt requests may carry an `isolationReceipt`; when
present, the runner validates it and stores its digest in transition history.

## Write-back receipts

`agent-worktree-writeback-receipt.v1` records the decision to apply or discard
changes from an isolated overlay. It binds workflow lineage, task id, attempt,
overlay digest, changed files, applied/discarded paths, operator authorization
and a receipt digest.

The receipt is runtime-agnostic. It can describe a container overlay,
temporary checkout or other isolated boundary, but ALK does not require a
specific container runtime and does not introduce a second sandbox schema id.
Runtime containment remains `agent-sandbox-receipt.v1`; write-back only
describes repository changes crossing back into the main worktree.
