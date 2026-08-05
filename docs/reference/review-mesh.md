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

Release 1.40 defines only contracts and validators. It does not recommend a
mode, create reviewer assignments, launch adapters, import reviewer output or
enforce quorum. Those steps are separate optional layers.

## Stable schemas

- `agent-review-mesh-profile.v1`
- `agent-review-mesh-assignment.v1`
- `agent-review-mesh-result.v1`
- `agent-review-mesh-synthesis.v1`
- `agent-review-mesh-quorum-receipt.v1`
- `agent-review-mesh-quorum-validation.v1`

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
