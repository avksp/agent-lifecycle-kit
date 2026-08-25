# Acceptance criteria

| ID | Requirement | Evidence | Deterministic acceptance |
| --- | --- | --- | --- |
| `AC241-IDENTITY` | `R241-IDENTITY` | `EV241-IDENTITY` | Missing, empty, same-actor and same-run worker identities all fail with stable lifecycle errors before any ACCEPTED, REWORK, CONTRACT_CHANGE or BLOCKED outcome mutation; a distinct declared reviewer passes. |
| `AC241-REVIEW` | `R241-REVIEW` | `EV241-REVIEW` | A review without `reviewId` fails with `task-review-invalid` before any state or event-log byte changes; no raw `KeyError` reaches CLI output. |
| `AC241-SCHEMAS` | `R241-SCHEMAS` | `EV241-SCHEMAS` | Every registered schema has unique `required` entries and both plan-manifest schemas pass Draft 2020-12 meta-structure checks available without a runtime dependency. |
| `AC241-CONSISTENCY` | `R241-CONSISTENCY` | `EV241-CONSISTENCY` | The same traceability mutation is rejected by plan check, plan verify, workflow run and adoption with a completeness code; runtime-only lock/quorum failures remain separately typed. |
| `AC241-PUBLICATION` | `R241-PUBLICATION` | `EV241-PUBLICATION` | Package, plugin, changelog, tag and Release 2.5 predecessor metadata consistently identify `2.4.1`. |
