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

Release 1.41 added deterministic recommendation advice. Release 1.42 adds the
semi-automatic layer around it: assignment packets, reviewer result import,
synthesis and quorum validation. ALK still does not run reviewer adapters; the
operator or host wrapper runs them and returns evidence for import.

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

## Assignments, results, synthesis and quorum

After a reviewed plan opts in, ALK can coordinate Review Mesh evidence without
becoming a model broker:

```bash
agent-lifecycle review-mesh assign --intake adapter-task-start.json \
  --mode leader-draft-multi-review --phase plan-review \
  --assignment-id RM-1 --reviewer-id claude-reviewer --out rm-assignment.json

agent-lifecycle review-mesh import-result --profile rm-profile.json \
  --assignment rm-assignment.json --reviewer-output reviewer-output.json \
  --out rm-result.json

agent-lifecycle review-mesh synthesize --profile rm-profile.json \
  --result rm-result-a.json --result rm-result-b.json --out rm-synthesis.json

agent-lifecycle review-mesh quorum --profile rm-profile.json \
  --synthesis rm-synthesis.json --min-reviewers 2 --out rm-quorum.json
```

Assignments are compact packets for host-owned reviewer execution. Imported
results redact secret-like markers and reject local absolute paths unless the
plan explicitly allows local evidence references. Synthesis records agreement,
conflicts, accepted findings, rejected findings and unresolved findings.
Quorum receipts can block freeze, implementation audit or final audit only when
the frozen plan declares Review Mesh as required for that phase.

For command-by-command examples for common tasks, see the
[Review Mesh workflow cookbook](../guides/review-mesh-workflow.md).

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
