# Plan continuity

Plan continuity covers coordinated work where a lifecycle plan references more
than one repository or needs a compact handoff for independent review. The
single-repository lifecycle remains the default; plans without
`repositoryReferences` pass continuity checks with zero references.

Repository references are explicit and bounded:

- each reference has an `id`, `repoId`, `owner`, `access` and optional relative
  `paths`;
- `access` is either `read-only` or `write-scoped`;
- `write-scoped` references must list paths;
- local absolute paths and traversal are rejected.

```bash
agent-lifecycle plan refs-check --manifest <plan.manifest.json>
```

Frozen plans can be snapshotted into an immutable content-addressed receipt.
The snapshot binds the manifest digest, base revision, specification digest,
acceptance digest and repository-reference digest.

```bash
agent-lifecycle plan snapshot --manifest <plan.manifest.json> --out <plan-snapshot.json>
```

Before a team resumes work from a saved snapshot, reconciliation compares the
snapshot with the current manifest. Matching input passes. Drift fails closed
with a concrete classification so the operator can create a new plan revision
instead of continuing from contradictory state.

```bash
agent-lifecycle plan reconcile --manifest <plan.manifest.json> --snapshot <plan-snapshot.json>
```

Reviewer handoff renders a compact packet with the plan identity, base
revision, repository-reference summary, workstream owners and acceptance ids.
It omits full requirement prose so small local models can review routing and
ownership without consuming the whole plan. Full artifacts remain the source of
truth for final review.

```bash
agent-lifecycle plan handoff --manifest <plan.manifest.json> --snapshot <plan-snapshot.json> --out <handoff.json>
```

Fresh-context handoff is a recipe over these artifacts, not a separate state
transition. A resumed worker may cite the handoff, status view, event feed or
progress view as evidence, but default lifecycle state does not change until a
normal workflow command records an operation.
