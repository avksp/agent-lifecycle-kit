# Developer overview

Release 2.4.1 is a narrow correctness and security patch over `v2.4.0`.

The workflow fix belongs in `workflow/reviews.py`, the common boundary used by accepted, rework, contract-change and blocked outcomes. Validation must reject missing identity before artifact commitment or state mutation. `_mark_task_accepted` remains a mutation helper, not the first validator of `reviewId`.

The schema defect is caused by the local plan-schema helper prepending `schemaVersion` to a caller list that already contains it. Correct the plan schema definitions and add a registry-wide test that recursively rejects duplicate strings in every `required` array. Do not silently deduplicate arbitrary schema input at read time.

Plan completeness and adoption already share `validate_plan_completeness` in 2.4. The patch adds regression evidence only; runtime lock, packet and Review Mesh checks remain adoption responsibilities and must not be mislabelled as completeness divergence.

## Freeze rule

Close independent S2 findings, increment `planRevision`, rerun structural and full-suite gates, then generate `agent-plan-lock.v2` for the final audited revision only.

