# Implementation audit

Template status: DRAFT-ONLY.
Review gate: required.
Freeze gate: not applicable; this audits completed frozen-scope work.

## Task

Audit the completed implementation against the frozen plan and evidence.

## Inputs

- Plan manifest:
- Plan lock:
- Workflow state:
- Task id:
- Task result:
- Task review:
- Optional quorum receipt:

## Check

- Changed files match write ownership.
- Acceptance criteria are covered.
- Evidence is fresh and bound to the task attempt.
- Tests and validators prove the intended behavior.
- No forbidden writes, secrets or local path leaks are present.
- Remaining findings have an explicit severity and disposition.

## Expected output

- Findings first.
- Acceptance coverage matrix.
- Validation outcomes.
- Verdict: accepted, rework, contract change or blocked.
- Whether refreeze is required.
