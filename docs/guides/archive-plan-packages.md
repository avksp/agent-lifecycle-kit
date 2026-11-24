# Archive a closed local plan package

Use `project archive` to copy a closed local package to a private ZIP outside
its Git worktree. Keep the project idle during the operation.

Prepare a catalogue that lists the packages and predecessor edges in the
project scope you own. Include active entries because they can reference
completed packages. Supply the exact SHA-256 of the catalogue bytes.

```json
{
  "schemaVersion": "agent-local-package-catalogue.v1",
  "scope": "my-project",
  "complete": true,
  "packages": [{
    "id": "sample",
    "manifest": "tasks/sample/plan.manifest.json",
    "predecessorIds": [],
    "state": "work/sample/run.state.json",
    "proof": "work/sample/final-proof.json"
  }]
}
```

Use repository-relative input paths. A package without a run can omit
`state` and `proof`. A started run without final proof can omit `proof`.
Mark the catalogue complete only when it includes every package and
predecessor edge in the named scope. ALK checks the supplied scope.

```sh
agent-lifecycle project archive inventory --catalogue work/catalogue.json --catalogue-sha256 SHA
agent-lifecycle project archive create --catalogue work/catalogue.json --catalogue-sha256 SHA \
  --inventory-digest DIGEST --package sample --out /private/archives/sample.zip
```

Use a fresh ZIP name in an existing directory you own. The project root,
its ancestors, and its descendants are refused. A fresh archive requires a
bound COMPLETE proof and untracked, ignored regular files. Keep plan and
work roots disjoint. A large completed package can exceed the snapshot
limits of 1,024 entries, 8 MiB per file or 64 MiB total.

Check `archive-manifest.json` inside the ZIP for exact paths, sizes and
SHA-256 values. The command preserves the source. Storage reclamation
requires a separate operator decision. If publication fails, inspect the
destination before retrying with a fresh name.
