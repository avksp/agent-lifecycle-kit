# Ordinary independent audit and provenance

Release 2.16 supports procedural independent source reviews using an existing
host. A coordinator preserves the result it actually received, the reviewer
and invocation identity, and the exact assigned source, dependencies and test
inputs. An author-written PASS is insufficient. Records on the same OS account
do not establish protected origin or prove every byte visible to the model.
`DECLARED` provenance does not become `ATTESTED` through this route.

The experimental R11 review producer, funding, worker, collector, publication
and native-admission entrypoints are disabled before side effects. Historical
records remain available for inspection. They cannot enable the ordinary route.
The cumulative cost ledger and durable attempt-result functions remain active.

## Review records

The reviewed policy and closed schemas are in the release plan's
`ORDINARY-AUDIT-*` files. Private runtime records live under
`work/release-2-16/evidence/ordinary-audit/`. Each review has an immutable
`assignment.json`, `admission.json`, initial `request.txt`, and assigned
`test-evidence.json`. Source paths are normalized, ordered, unique, bounded and
read without following symlinks. Record files are private and created once.

`publish_observed_result` is called by the coordinator handling an actual host
result. It retains `raw-result.txt` separately from the normalized report,
records the observed adapter/session/invocation, and rejects the author's or
coordinator's session. Partial publication and failed reports never authorize
launch. The original returned result must agree with the report's verdict,
findings, coverage and predecessor identities.

An AREA result covers one fixed scope. The separate END_TO_END invocation must
bind all accepted AREA report digests in their assigned order, cover their exact
source union, and include every required bootstrap implementation file. Its
test evidence names the actual C34/C35 commands, individual case outcomes and
stored output bytes. Closing the retained observer/timeout finding additionally
requires an explicit independent disposition and current regression evidence.
An earlier failure is never rewritten as a success.

Completed AREA evidence remains reusable after its original review window when
all assigned inputs and origin remain unchanged. A legitimate later financial
reservation does not alone invalidate it. Changed source, dependencies or test
inputs invalidate affected coverage and the integration result. Unknown usage
stays null with its full hold; this route does not refund overruns or restart
failed work automatically.

## Current task admission

A review PASS alone cannot start a task. `integration-selection.json` selects
the exact independent integration report and ordered AREA review IDs. A fresh
task receipt additionally binds the reserved run/task/attempt/operation, current
state, plan and lock, profile, actual selected executable, source and test
snapshot, financial head, and original UTC and monotonic deadlines.

Before the managed launch, the coordinator prepares a private
`tasks/<task-key>/admission-request.json` in the ordinary-audit store. The key is
the canonical digest of `{runId, taskId, attemptId}`. Its closed fields are:

- `schemaVersion: alk-ordinary-fresh-admission-request.v1`;
- `runId`, `taskId`, `attemptId`, `operationId`, `planDigest`, `lockSha256`;
- `profileSha256`, `selectedBinarySha256`, `integrationReportSha256`;
- `priorHeadSha256`, `sourcePath`, `tokenCap`, `protectedCloseoutTokens`,
  `timeoutSeconds`.

The request authorizes one explicit finite coordinator window after a closed
predecessor. `sourcePath` names its new
`work/release-2-16/enforcement-decision/r<N>-<name>/admission.json`; N must increase.
The current cumulative ledger supports caps up to 300000 tokens, with a positive
closeout reserve below the cap. The metadata timeout is at most 120 seconds.
There is no default admission or implicit prior-window close.

After the launcher creates the real intent, ALK fills its digest and original
clocks once, persists the admission and advances the existing cost ledger.
Duplicate files or an uncertain ledger transition refuse; they do not retry or
release the hold. The coordinator later closes this same window through the
existing ledger closeout operation, retaining unknown expenses and artifacts.

The direct and unified Codex routes use the same final pre-spawn verifier.
Changes after preparation, expired clocks, changed ledger heads and consumed
attempts refuse before the process-start claim. Existing explicit route/claim,
limited input-fit, configuration, process observation and cleanup checks remain
required. The receipt grants only `ALLOW_THIS_ATTEMPT`; it never grants protected
closure, complete host-context qualification or full financial enforcement.

## Evidence limits

Component tests use real private files, source/output digests and task-state
checks, with explicit controlled boundaries for host observations and the cost
ledger. They do not establish an independent implementation audit, an actual
Codex run, a full C34/C35 release evidence receipt, or final release readiness.
Other adapter, retention, platform and product release conditions still apply.

## Reviewer result imports

Redaction covers sensitive JSON keys inside findings and command metadata, as
well as the imported schema label. Result validation requires every usage field
and checks status, subject, reviewer and findings against the nested receipt.
Recomputing digests cannot waive a failed command or supply a missing measurement.
An unknown resource does not excuse a cap overrun in another observed resource.
Distinct identity hashes in an import remain comparison data: when independence
is required, both receipt layers say `NOT_PROVEN` and native validation refuses
acceptance until independently observed evidence is available.

The public Review Mesh importer rejects malformed containers, findings, statuses,
resource values and conflicting assignment bindings before producing output.
Supported top-level or nested `bindings` identities must match the supplied
assignment; a nested `subject` or `reviewer` may supply an exact subset of its
assigned fields. Imported findings retain their fields, subject to the existing
secret and local-path redaction policy. Import never grants independence or quorum.

`commandOutcomes` is an optional list of objects with a unique nonempty
`commandId`, `status` (`PASS` or `FAIL`) and integer `exitCode`. A nonzero code
cannot claim `PASS`. A failed command remains in the output and makes the result
`FAIL`, including when the enclosing input claims `PASS`; `WAIVED` is rejected.

Each omitted or null resource measurement stays null in `budgetUsage`. Such a
result has `budgetUsageStatus: UNAVAILABLE`, no `crossCheckReceipt`, and no round
participation. Findings remain readable, but the normal result validator returns
FAIL for unavailable usage, so the candidate cannot authorize work. Explicit
measured zeros remain zero and retain the ordinary numeric receipt. No unknown
measurement is replaced with zero, and import does not release financial holds.

Review Mesh profile permissions must agree with the nested cross-check profile, and an assignment cap must match its bound profile. Repaired digests do not override those joins. Result import rejects secret-bearing or local-path dictionary keys instead of renaming them and risking collisions. Bound assignment metadata containing secrets or local paths is refused before emission; import never redacts and re-signs that authority. Safe finding fields, unavailable usage and original inputs retain their existing semantics.

When an authoritative Review Mesh profile is supplied, assignment/result/synthesis/quorum validation checks the complete profile and joins both its identifier and digest. The nested cross-check receipt also binds its own profile identifier. Standalone validation without a profile remains structural. Quorum validation recomputes count/role consistency; structural PASS for a valid failed receipt is not quorum acceptance. The pass helper requires a successful receipt with satisfied quorum and no unresolved blocking findings.

Result import checks bound profile metadata, including nested profile identifiers, before emitting a receipt. Sensitive identifiers are refused without changing their digests. Overlapping bindings and assignment matches compare complete JSON values and types recursively; supported subject/reviewer subsets remain accepted, while nested booleans cannot replace numeric identity values.

Validated bindings retain their original authority values, including safe URL spelling and literal redaction placeholders; finding content may still be normalized. HTTP URL spans whose authority cannot be validated are redacted in full, even when URL parsing itself succeeds.

Host and port validation also applies when userinfo is present. A redacted username does not permit a missing host or malformed port; valid DNS and IPv6 authorities preserve their safe path and query.

URL shielding chooses tokens absent from the original text and restores generated spans in one pass. Literal diagnostic tokens and tokens within restored URL paths remain ordinary content.

With an authoritative profile, all Review Mesh receipt validators require a mode enabled by that profile, including result, synthesis and quorum. A globally recognized mode excluded from the supplied profile cannot pass quorum acceptance; standalone validation remains structural.
