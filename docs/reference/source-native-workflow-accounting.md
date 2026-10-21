# Source-native workflow accounting

Release 2.21 adds opt-in command measurements and preparation checks at selected
ALK boundaries. These observations do not issue workflow permission or prove
that ALK controls every call made directly by a host.

## Command and token observations

Pass `--measure-request <request.json> --measure-out <receipt.json>` **before**
the ordinary CLI command. A bounded request binds selected source files and a
declared base revision. The command still runs in its existing process; no model
or subprocess is added. Without these options, ordinary output remains unchanged.

Wall time and self CPU use monotonic process observations. Nested spans have
inclusive and exclusive values; aggregate exclusive values to avoid counting a
child twice. The base revision remains `DECLARED_BASE`; selected file bytes are
verified separately. A receipt does not attest the whole Git tree or child CPU.
If receipt publication fails after a command effect, keep the effect and original
output; do not automatically repeat the command.

Missing model usage stays `UNAVAILABLE`. An explicitly observed zero differs
from a missing value. Cache-read/non-cache input, output and derived totals retain
their basis. Known usage plus an unknown contributor produces a partial total.
Allocations, conservative holds and measured provider spend are different values.

## Provider and reviewer readiness

`agent-lifecycle adapter provider-preflight --profile .alk/host-launch/<name>.json`
performs bounded local inspection without a model request. An executable alone
does not prove authentication, configuration or model availability. The CLI has
no option to submit a JSON file that attests these properties. Missing native
qualification returns `UNAVAILABLE`; success would not assure quota or a later
request. Portable output contains fixed statuses and digests, without raw config,
credentials, prompts or private paths.

Trusted adapter integrations may supply already qualified, current observations
to `provider_preflight`. Their source and authority remain the integration's
responsibility; a caller setting `qualified=true` is not host attestation.

`review_mesh.preflight.reviewer_preflight` checks current selected source bytes,
packet/render fidelity, bounded input and the exact qualified argv identity. A
prompt asking a reviewer not to write is insufficient. The selected route needs
existing qualified host restrictions or a bounded isolated-workspace route;
missing restrictions refuse before generation. ALK adds no sandbox or provider
client. Local fixtures qualify integration mechanics, not production host support.

## Preparation admission

`contracts.preparation_policy` is the single pure decision function. It consumes
already qualified goal/phase/source, grant, complete chain, progress, readiness,
repeat justification and finite limits. It performs no I/O and grants no authority.

The trusted `JournalPreparationAdmission` integration uses the existing H04
Journal. Its qualifier is a trusted in-process source port, not reviewer output
or a CLI policy file. Refresh grant, applicability, provider restrictions and
progress through their existing validators; do not manufacture qualification.

An operation's existing attribution field stores bounded preparation metadata
**before that operation is authorized and bound**. It records stable goal/phase,
source, quantity, charged-work upper bound and semantic round. No table, store,
event type or financial interpretation is added. Reservations retain their
original upper bounds across failures, delivery recovery and compaction.
Conservative charged-work upper bounds are not measured CPU or actual spend.

`Journal.bounded_prefix` requires exact scope/revision/ordinal and finite row/UTF8
byte limits. It checks metadata sizes before loading payloads in one existing
transaction. Missing, oversized, incomplete, compacted or drifting history refuses;
it cannot qualify as zero prior work. Existing `events`, snapshot and writer APIs
remain unchanged. Selected admission never uses unbounded `events(scope)`.

Fresh expected-revision reservation and a unique claim guard the existing effect.
Replays cannot generate twice. A crash after a durable claim retains the hold;
existing Journal rebuild marks uncertain work incomplete until authoritative
recovery. No no-dispatch refund is inferred. All prior reservations, requests and
charged-work bounds remain counted when a window or job is renamed. A genuinely
new goal needs an explicitly qualified scope change; previous financial exposure
still counts. Exact supported quantity labels are retained; unsupported whole-host
limits refuse. Direct host calls outside selected ALK routes remain outside this
guarantee.

The default stop is two completed nonproductive semantic rounds. Artifact/hash
churn does not advance a goal. Valid new audit/diagnosis/evidence may advance a
read-only goal. An authorized bounded wait does not consume a semantic round and
does not permit expensive generation while waiting. A finite approved threshold
override is distinct from another budget or “continue”. Native task/run deadlines
are checked separately and never restarted by these checks.

Required integration/final chain slots, permissions and declared prerequisites
must be current before an expensive effect. Ordinary covered steps reuse their
existing grant. Justified repeats name missing/invalidated input and expected
benefit; otherwise admission returns `REPEAT_NOT_JUSTIFIED`.

Declared execution chains reuse the 2.20 actual-target inspector immediately
before controlled effects. Bind the real root/source/plan and complete outputs,
including ignored state and event paths. A successful disposable clone does not
qualify the actual target. Planning-only checks require no implementation checkout
or service. Core launches no project services. Environment-only repair preserves
applicable reports/locks and costs; changed reviewed source needs existing
applicability checks. A readiness result is not a filesystem lease or permission.

The optional trusted integration is consumed by local profile preflight/execution,
generic descriptor refusal, Review Mesh preflight and external-job generation.
Unselected legacy routes retain their previous limited semantics. Generic
descriptor launch remains disabled. Existing exact routes that cannot qualify
the composed boundary refuse rather than bypass their original restrictions.

## Response recovery

`agent-lifecycle adapter external-job recover --request <request.json>` validates
and retrieves the same complete immutable attempt, including artifact bytes and
the original result/usage identities, without generation. `external-job run
--recover-existing` checks an existing same-attempt response before invoking argv.
Recovered process diagnostics remain local; portable recovery contains the
validated semantic result. Retrieval does not add an independent voice or charge.

Live/unknown work, partial/malformed results and wrong source/job bindings refuse.
Generation retries default to zero. The selected route permits only an explicitly
qualified finite retry of a settled transient exit 75 with no output, proven
cleanup, unchanged subject, named corrected input/benefit and remaining cumulative
allowance. It does not automatically loop. Timeout, bad auth/config/argv, malformed
response or unchanged invalid output does not acquire a full retry. Cancellation
acknowledgement is not proof that remote work terminated.

## Comparisons and later activation

The tracked 2.21 baseline fixtures separate actual observations, synthetic local
mechanics and missing data. Compare only matching workload/environment/timing
boundaries; external CLI startup measurements differ from in-process spans.
Do not infer tokens from bytes, holds or wall time, or advertise a savings
percentage from partial or synthetic data. Missing repeated unchanged-scope full
review data blocks 2.22 activation; missing real legacy S0/S1 ceremony data blocks
2.23 activation. These gates do not require buying a new model audit merely to
populate a number. Release publication and PyPI approval remain separate outcomes.

Selected reviewer launches bind the exact request/source, argv, resolved repository
root and complete UTF8 STDIN delivery into one invocation digest. The trusted
preflight receipt is closed and rechecked immediately before the existing process
sink. A PASS for another invocation or missing input transport cannot launch it.
The receipt qualifies existing restrictions; it does not create a sandbox.

Each new attempt durably stores bounded private `response.stdout` and
`response.stderr` before its terminal result. The host-local
`load_external_job_response` reader verifies those bytes against the original
result for parsing/import; the portable CLI never prints the raw body. Legacy
metadata-only attempts remain readable, but cannot qualify as recoverable complete
responses. Missing or changed bytes refuse without generating a replacement.
Portable recovery is limited to 64 KiB and rejects unsupported or sensitive extras
in request/status/result/artifact records instead of rewriting an accepting
identity. Original private records and reported usage remain unchanged.
