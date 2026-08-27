# Evidence plan

## EV27Q-QUALITY

Run the repository's locked Ruff, mypy and coverage producer against the
accepted v2.6.0 base SHA, then validate its receipt. Require `status: PASS` from
both artifacts and an empty blocker list. Do not update the policy or any
baseline.

## EV27Q-BEHAVIOR

Run the existing focused tests for review-round contracts, statistical evidence,
finding checks, review verdicts, audit-optimization schemas, audit
efficiency/optimization/samples, Review Mesh result import/synthesis and
specification completion. Then run complete unittest discovery. Compare any
touched expected object or stable error code to the pre-remediation tests; no
expected values may be loosened merely to pass.

## EV27Q-BOUNDARY

Audit the candidate diff against `5ca88f8fade33171ce9890730a3c95dbdff91bd6`.
Reject changes outside the declared write set and reject any change to quality
policy, baselines, schema identifiers, required fields, severity sets,
acceptance decisions, thresholds, output fields or release metadata. Type
narrowing must follow a runtime guard or use an already validated value.
Require the task ownership receipt and independent implementation audit to
classify every changed path as task-owned; any forbidden, read-only, lead-owned
or unowned product path blocks acceptance. Writable test paths may only add or
tighten regression coverage; removing or weakening an assertion is a finding.

## EV27Q-REGRESSION

Run dependency and complexity validators, tracked-release neutrality, and the
full suite. After push, require the GitHub `python-quality` jobs for Python 3.11,
3.12, 3.13 and 3.14 to pass on the exact final commit. A rerun cannot substitute
for a deterministic local quality PASS.
