# Review Mesh

Review Mesh is an optional contract layer for multi-reviewer work. It is useful
when a plan wants more than one independent view on planning, research or
implementation evidence, but it is not part of the default lifecycle.

The supported mode ids are:

- `leader-draft-multi-review`: one lead creates a draft plan or research result
  and independent reviewers check it.
- `parallel-research-synthesis`: several reviewers prepare independent
  research or plan candidates before synthesis.
- `implementation-audit-panel`: several auditors review implementation
  evidence after work is complete.

Release 1.41 adds deterministic recommendation advice. It can suggest a mode
from task text, intake receipts or plan manifests, but it still does not create
reviewer assignments, launch adapters, import reviewer output or enforce
quorum. Those steps are separate optional layers.

## Stable schemas

- `agent-review-mesh-profile.v1`
- `agent-review-mesh-assignment.v1`
- `agent-review-mesh-result.v1`
- `agent-review-mesh-synthesis.v1`
- `agent-review-mesh-quorum-receipt.v1`
- `agent-review-mesh-quorum-validation.v1`
- `agent-review-mesh-recommendation.v1`

## Recommendation advisor

Use the advisor when the operator wants to know whether extra review is worth
the cost before accepting it into a plan:

```bash
agent-lifecycle review-mesh recommend --text "Research the architecture and write a plan"
agent-lifecycle review-mesh recommend --file task.md
agent-lifecycle review-mesh recommend --intake adapter-task-start.json
agent-lifecycle review-mesh recommend --manifest plan.manifest.json
```

The receipt can recommend `off`, `leader-draft-multi-review`,
`parallel-research-synthesis` or `implementation-audit-panel`. It records
phase coverage, reasons, required reviewer count, token/resource caps,
provider-neutral model class hints and a skip rationale when `off` is enough.

The recommendation is not execution authority. It does not activate blocking
gates, create assignments, enforce quorum, start model calls or launch host
CLIs. A reviewed frozen plan must opt in before Review Mesh can become required
evidence. It does not recommend bypassing review/freeze or asking ALK core to
launch adapters.

## Contract rules

Review Mesh is fail-closed and provider-neutral:

- disabled by default;
- enabled only by an explicit reviewed plan;
- advisory unless the frozen plan opts into blocking use;
- budgeted by tokens, invocation count and wall-clock resources;
- not a canonical USD-cost surface;
- independent by neutral `hostIdentityHash` and `modelIdentityHash` values;
- concrete provider, model and account names are not portable identity fields.

The implementation reuses the existing optional cross-check semantics for
budget caps and independence evidence. Review Mesh adds lifecycle-specific mode
ids and receipts around those checks rather than creating a second review
engine.

## Boundaries

Review Mesh does not bypass specification review, plan freeze, implementation
audit or final proof. It can add evidence only when a task or plan asks for it.
Host CLIs, provider credentials, model selection and reviewer execution remain
adapter-owned or operator-owned.
