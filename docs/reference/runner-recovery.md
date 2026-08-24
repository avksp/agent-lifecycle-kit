# Historical runner recovery records

Runner recovery receipts are historical evidence, not an execution controller.
Release 2.0 keeps their schemas readable so an existing archive can be
converted without granting it authority.

Use `workflow migrate-runner-artifact` for an explicit read-only conversion.
The converter validates the bounded input, preserves the source digest, writes
one private no-replace output, and records unmapped fields instead of guessing
workflow state. The result is non-authoritative and cannot authorize a retry,
resume or production action.

Current recovery is owned by workflow state: task attempt history, task review,
`REWORK`, external-action pause/resume, and final-audit routing. Start from the
current workflow state and frozen plan rather than reconstructing authority from
a historical runner snapshot.

The compatibility path remains required throughout 2.x. A future removal needs
a separate compatibility audit and a major-version decision no earlier than
3.0.

Fresh-context handoff is recipe/evidence only. It is evidence over historical
artifacts and does not mutate lifecycle state by default; a normal workflow
command must record any operation.
