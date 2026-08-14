# Project principles and plan deltas

Long-running projects need two different kinds of continuity:

- project principles describe stable defaults and constraints that help an
  agent understand the project;
- a plan delta explains what changed between two reviewed plan revisions.

These artifacts make the project easier to hand over without creating a second
source of truth. The frozen plan and matching lock still control implementation
authority.

The public contracts are `agent-project-principles.v1`,
`agent-project-principles-validation.v1`, `agent-plan-delta.v1` and
`agent-plan-delta-validation.v1`.

## Project principles

Principles are a small JSON artifact referenced by the project profile. They
can describe architecture preferences, compatibility expectations, quality
priorities and other durable project constraints. They cannot contain prompts,
provider or model names, credentials, executable instructions or absolute local
paths.

Example `docs/project-principles.json`:

```json
{
  "schemaVersion": "agent-project-principles.v1",
  "principlesId": "checkout-project",
  "revision": 1,
  "entries": [
    {
      "id": "public-contracts",
      "category": "architecture",
      "statement": "Keep public contracts additive and versioned.",
      "rationale": "Existing integrations must continue to read older envelopes."
    }
  ],
  "authority": {
    "principlesRole": "defaults-and-constraints",
    "sourceOfTruth": "frozen-plan-and-lock",
    "semanticReview": "independent-review"
  },
  "source": {
    "kind": "project-local",
    "path": "docs/project-principles.json"
  },
  "productionPromotionClaimed": false,
  "principlesDigest": "<sha256-of-the-object-without-principlesDigest>"
}
```

Check the artifact without starting a model or host process:

```bash
agent-lifecycle project principles check \
  --file docs/project-principles.json \
  --project-root .
```

Reference it from `.alk/project-profile.json` with its digest:

```json
{
  "principles": {
    "path": "docs/project-principles.json",
    "digest": "<sha256>",
    "sourceOfTruth": false
  }
}
```

The profile carries only the path and digest. ALK does not copy the principles
text into an execution packet and does not let the reference lower a frozen
plan's risk, write scope, gates or evidence requirements.

## Plan deltas

A plan delta compares two explicit revisions. It reports additions, removals
and digest changes for requirements, writes, acceptance, evidence, budgets,
risks and gates. Documentation-only changes are reported separately and do not
automatically require a new implementation lock.

```bash
agent-lifecycle plan delta \
  --before path/to/plan-v1/plan.manifest.json \
  --after path/to/plan-v2/plan.manifest.json \
  --before-lock path/to/plan-v1/plan.lock.json \
  --after-lock path/to/plan-v2/plan.lock.json \
  --out work/plan-delta.json

agent-lifecycle plan delta-check \
  --delta work/plan-delta.json
```

The comparison is read-only. It blocks when package identity, revision order,
snapshot lineage or lock binding is inconsistent. If implementation authority
changed, the report sets `reviewRequired` and `newLockRequired` to `true`; it
does not create or approve either artifact.

## When to use it

Use principles for stable project context that would otherwise be repeated in
every task. Use a delta when a long-running project receives a new requirement,
changes a permitted file, tightens a budget, adds a gate or transfers work to a
new owner. The reviewer can then see the exact authority categories that need
fresh review before implementation continues.

See also [Project workflow profile](project-workflow-profile.md), [Plan
continuity](plan-continuity.md), and [System architecture](../architecture/system-architecture.md).
