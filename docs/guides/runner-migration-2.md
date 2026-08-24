# Migrate legacy runner artifacts

Release 2.0 removes the public controlled-runner command surface. Existing
runner state, transition, snapshot and recovery JSON remains readable through
one explicit converter so archives can be retained without preserving a second
execution authority.

For current work, start from the frozen plan with `workflow run`; this guide is
only for converting historical runner artifacts.

## Convert one artifact

```bash
agent-lifecycle workflow migrate-runner-artifact \
  --input /path/to/legacy-runner-artifact.json \
  --output /path/to/legacy-conversion.json
```

The input is bounded to 1 MiB by default. The converter validates a supported
historical schema, checks its self-digest where defined, rejects symlinks and
unstable reads, and refuses to replace an existing output. The output is a
private conversion record with source SHA-256, source size, unmapped fields and
stable blockers.

## Authority rules

The conversion is read-only and non-authoritative. It always records
`authorityClaimed: false`, `stateWritten: false`, `modelCallsStarted: false` and
`hostLaunchStarted: false`. It never creates workflow state, resumes an attempt,
changes a plan, calls a model, launches a host or claims production promotion.

Use the current workflow state and frozen plan for new work. A conversion record
cannot satisfy task acceptance, final audit or publication gates.

## Failure handling

Unknown schema IDs, malformed or deeply nested JSON, stale embedded digests,
oversized input, changed-during-read files, symlink paths and existing output
files fail closed with a structured lifecycle error. Preserve the original
artifact and investigate the error before attempting a new conversion.

The converter remains part of the 2.x compatibility surface. Its removal is a
separate major-version decision and cannot happen before 3.0.
