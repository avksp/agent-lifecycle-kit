# Evidence index and imports

Evidence indexes are optional, disposable summaries over existing lifecycle
artifacts. They are useful when a reviewer or small local model needs to find
the right receipt without reading every artifact in full.

The index is not a source of truth. It is rebuilt from explicit
repository-relative artifact paths, stores digests and compact fields, and does
not return raw artifact content.

```bash
agent-lifecycle evidence index \
  --project-root . \
  --artifact evidence/final-proof.json \
  --out evidence-index.json

agent-lifecycle evidence search \
  --index evidence-index.json \
  --query final \
  --out evidence-search.json
```

Resource caps are part of the command contract:

- `--max-artifacts` limits how many artifacts can be indexed;
- `--max-input-bytes` limits how much input can be read;
- `--target-tokens` fails closed when the compact output is too large.

Planning imports are also optional. They convert one untrusted input file into
a draft ALK candidate and a validation receipt. The candidate remains
`DRAFT`, carries `freezeBlocked: true`, and still needs normal plan check,
independent review and explicit freeze before implementation.

```bash
agent-lifecycle import plan --source incoming-plan.md --out imported-plan.json
agent-lifecycle import check --candidate imported-plan.json
```

Adapter task intake uses the same review boundary for operator-facing adapter
work:

```bash
agent-lifecycle adapter task start --adapter codex --file task.md
agent-lifecycle adapter task start --adapter codex --task-text "Analyze code before implementing the feature"
```

The command writes `agent-adapter-task-start-receipt.v1`. It stores source
digest and byte count, not raw task text. Use `--candidate-out <path>` to save
the full draft planning import artifact for review.

Import blocks sensitive local paths and secret markers before building a
candidate. The command output uses the source digest and file label rather than
embedding absolute paths.

Skill improvement records are proposal artifacts only:

```bash
agent-lifecycle import proposal-check --proposal skill-proposal.json
```

A valid proposal must require review and must set `autoApply: false` and
`applied: false`.
