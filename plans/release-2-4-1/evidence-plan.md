# Evidence plan

## EV241-IDENTITY

Run ACCEPTED, REWORK, CONTRACT_CHANGE and BLOCKED fixtures through their public workflow routes. Independently remove `actor`, empty `actor`, remove `actorRunId`, empty `actorRunId`, match reviewer id and match reviewer run id. Each mutation must fail with a stable code before any review, outcome, blocker, contract-change request, state revision or event-log mutation. Positive fixtures use distinct non-empty identities. The non-accepting fixtures exercise `apply_task_review_outcome` and its `allow_non_accepting_outcome=True` path explicitly.

## EV241-REVIEW

Remove `reviewId` from accepted, rework, contract-change and blocked review fixtures. Assert a typed validation error, unchanged state bytes and unchanged event-log bytes. Exercise the public CLI boundary and assert no traceback or `cli-unexpected-error`.

## EV241-SCHEMAS

Walk all schemas returned by `list_schemas()`. Recursively inspect every `required` array and require unique strings. Assert the exact two formerly broken schema IDs and run the existing schema registry/plan manifest tests.

## EV241-CONSISTENCY

Apply one missing traceability owner, one final-gate link mutation and one invalid independence route to the same S2 fixture. Compare completeness blockers across plan check, plan verify, workflow run and adoption. Separately remove the lock and quorum receipt to prove those remain runtime integrity failures, not completeness results.

## EV241-PUBLICATION

Run the full suite, architecture/complexity gates, neutrality scan and publication validators for `2.4.1` / `v2.4.1`. Verify Release 2.5 names `release-2-4-1` before freeze.
