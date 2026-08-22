# Plan verification and integrity

`agent-lifecycle plan verify` is a read-only handoff check for an ALK plan
package. It composes the checks that a reviewer needs before a frozen plan is
used by the workflow: manifest shape, completeness, acceptance traceability,
repository references, workflow-state requirements, the lock and the complete
package inventory.

## Command

Run it from the repository that contains the plan package:

```bash
agent-lifecycle plan verify \
  --manifest tasks/release-1-79/plan.manifest.json \
  --package-root tasks/release-1-79 \
  --lock tasks/release-1-79/plan.lock.json \
  --acceptance tasks/release-1-79/acceptance-criteria.md \
  --state work/release-1-79/run.state.json \
  --repository-root . \
  --out work/release-1-79/evidence/plan-verification.json
```

The output is the `agent-plan-verification-receipt.v1` contract. `PASS` means
that the supplied package is internally consistent for the selected status and
state. `FAIL` contains structured blockers and does not authorize any code
change.

## What is checked

- The manifest conforms to `agent-plan-manifest.v1`.
- Requirements, acceptance criteria, evidence, final gates and workstreams
  form a complete, non-orphaned graph.
- Every authority path is a normalized repository-relative literal. Glob-like
  `*`, `?` and `[]` patterns, absolute paths, traversal and URI-like paths are
  rejected.
- A `FROZEN` plan has a matching lock. `DRAFT` and `REOPENED` packages may be
  checked without a lock, but a supplied lock must still match.
- A non-terminal workflow state requires a lock; terminal states
  (`COMPLETE`, `FAILED` and `CANCELLED`) do not create new execution authority.
- When package integrity is declared, the check delegates to the same
  `agent-plan-lock.v2` inventory used by the freeze layer. It does not create a
  second inventory algorithm.

## What it does not do

The command does not execute `validation.commands`, call a model, access a
network service, launch an adapter or host process, or change workflow state.
It is a deterministic handoff check, not an implementation audit and not a
release-promotion decision. Run `audit implementation` after task evidence is
available, and use `audit package` for the combined plan and implementation
handoff.

## Reviewer handoff

The person who prepares the plan can provide the manifest, acceptance
checklist, lock and workflow state to a different reviewer. The reviewer runs
`plan verify`, inspects the receipt and then performs the independent S2 or
implementation audit required by the plan. A failed check must be resolved in
the plan package and verified again; a successful text response from an agent
is not a substitute for the receipt.
