# Host-local token accounting

## Explicit protected operator requests

`workflow adopt-plan`, `workflow finalize` and `workflow continue` accept
`--requested-claim PROTECTED_ADOPTION_OR_CLOSING`. The current native operator
route is unavailable: these requests exit 2 with `UNSUPPORTED_OPERATOR_ROUTE`
before opening state, manifest, audit or proof files. Managed launch rejects the
same `requested_claim` before loading the host profile or starting a process.
This refusal grants no bootstrap authority, protected window or financial permit.

Omitting the option, or selecting `ORDINARY_LIMITED`, preserves existing ordinary
validation and execution gates. An ordinary request is not a protected fallback.
The existing Codex bounded-input claim remains a separate managed-launch request.

## Closed-run maintenance

`alk workflow maintenance --authority /absolute/private/maintenance-authority.json
--authority-sha <sha256> --candidate-limit 32 --deadline <UTC>` invokes the
existing journal retention boundary. Only a fully closed financial run becomes
eligible after 30 days. Incomplete runs and financial exceptions retain their
details; summaries, costs, deduplication and closure records survive collection.

The private root is the canonical authority file's parent; the journal, file
identities, frozen manifest/lock and writer digest come from that pinned file.
The private `maintenance-authority.json.writer.json` companion contains exactly
the writer's `ref` and `digest`, whose canonical object digest must equal
`writerDigest`. Retain this companion after collection: SQL detail may no
longer contain the original writer. Both files must be owned regular files with
mode 0600 under the owned 0700 root. Journal/private-root overrides refuse.

Each invocation uses real UTC, its original deadline and a maximum 60-second
work window. Its result contains hashed run IDs, pending/overdue outcomes and
the next due time; it contains no prompts or responses. Unsupported safe file
operations refuse before deletion. A `PARTIAL` result retains enumerable
obligations for a later scheduled invocation. `COMPLETE` means the bounded
command finished; it does not certify installation, full financial coverage or
an independently protected operator. Scheduler installation and the target
probe are separate release requirements.

ALK keeps model and provider telemetry outside the portable core. An adapter
may declare a local usage normalizer that reads one bounded host artifact and
emits the existing `agent-lifecycle-model-usage-receipt.v1` contract. The
descriptor declaration uses `adapter-local-usage-normalizer.v1`.

This separation answers two different questions:

- the adapter normalizer determines which counters the host actually reported;
- the core validates provenance, route binding, budgets and whether those
  counters are acceptable evidence for S1/S2.

## Evidence levels

| Status | Meaning | Accepted for S1/S2 |
| --- | --- | --- |
| `UNSUPPORTED` | No adapter-local normalizer is declared. Core may expose a conservative estimate. | No |
| `FIXTURE_ONLY` | The parser is covered by bounded fixtures, but no live host range has qualified its output. | No |
| `QUALIFIED` | A declared host range and independent qualification evidence cover the normalizer. | Yes, only for `source: host` and `status: ATTESTED` |

The adapter support level and token-normalizer status are separate. For example, Qwen
Code can remain a `VERIFIED` adapter while its newly factored usage normalizer
is still `FIXTURE_ONLY`. Existing lifecycle evidence is not silently reused as
qualification evidence for a new parser contract.

## Receipt binding

The adapter emits model usage as a sidecar inside a host-operation output. It
does not change `agent-host-operation-receipt.v1`. The sidecar binds:

- operation id and route decision digest;
- adapter id and host;
- provider-neutral model class and a hash of the host-local model binding;
- source artifact SHA-256, byte count and format, without a local path;
- normalizer status and source-file digest.

Raw JSONL, prompts, responses, secrets and local paths are not copied into the
portable receipt. Session ids are retained only when they match the bounded
opaque-id policy.

## Reference adapters

| Adapter | Artifact | Normalizer status |
| --- | --- | --- |
| Gemini CLI | `stream-json` | `FIXTURE_ONLY` |
| Kimi Code | `stream-json` | `FIXTURE_ONLY` |
| Qwen Code | `stream-json` | `FIXTURE_ONLY` |
| Other bundled adapters | Not declared by this contract | `UNSUPPORTED` |

All three reference parsers are loaded from
`adapters/<adapter>/usage_normalizer.py`. The adapter runner and live harness
use that same file through a contained loader. The loader rejects traversal,
symlinks and descriptor/path mismatches.

Validate declarations and parser boundaries:

```bash
python tools/release/validate_host_usage_normalizers.py \
  --adapter-root adapters \
  --evidence work/validation/host-usage-normalizers.json

agent-lifecycle adapter validate \
  --descriptor adapters/qwen-code/adapter.descriptor.json
```

Validate a qualified model-usage receipt against its route and budget:

```bash
agent-lifecycle model usage-check \
  --receipt work/run/model-usage.json \
  --route-decision work/run/model-route.json \
  --budget-targets conformance/core/budget-targets.v1.json
```

Fixture output is exact for that fixture, but it is still `ESTIMATED` evidence
for lifecycle gates. A status label cannot promote it to host attestation.

## Conservative fallback

When exact host evidence is unavailable, core fallback uses a visible
one-token-per-source-byte upper bound. This is deliberately conservative and is
labelled `source: core-estimate`, `status: ESTIMATED`. Aggregation classifies
usage as attested only when both `source: host` and `status: ATTESTED` are
present.

Token accounting remains resource accounting, not price accounting. A host may
report monetary metadata, but ALK has no canonical provider price catalog.

### Accounting profile input preflight

`profiles/accounting-adapter-capabilities.v1.json` supplies the twelve frozen
expectations. Its `EXPECTED_NOT_OBSERVED` entries preserve each candidate and
source ceiling; they are not accepted runtime profiles. Archived sources remain
byte-pinned release inputs under `work/`, not runtime compatibility evidence.

From the release checkout, using a supported Python version, check the catalog:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 tools/release/validate_accounting_adapter_profiles.py \
  --manifest tasks/release-2-16/plan.manifest.json --catalog-only \
  --evidence work/release-2-16/accounting-catalog-preflight.json
```

Use `--preflight --profiles-root <evidence-root>` instead of `--catalog-only` to check selected
profile envelopes, exact expectation/version/route/case bindings, claim ceilings
and bounded file-reference graphs. Invalid or missing inputs fail. Symlink
references, escaping paths, changed bytes, conflicting references and duplicate
JSON keys fail; unavailable safe file reads also fail. Outputs are create-only.

The report has schema `alk-accounting-profile-preflight.v1` and at most
`STRUCTURE_VALID_ONLY`. A selected-profile invocation returns exit 2 even when
input checks succeed: observation origin, independent review provenance,
qualification and actual pre-dispatch refusal still need their own proof.
Supplied PASS/ACCEPTED labels grant neither capability nor dispatch authority.
This diagnostic is not the accepting EV216-ACCOUNTING-ENFORCEMENT receipt or the
completed P-FINAL-VALIDATOR. Partial accounting grants no financial closure or
permission for thirty-day raw retention.

## Accounting request refusal before launch

An explicit `accountingCapabilityRequest` in planning advisory or managed-launch risk input is refused before process dispatch until final profile qualification and dispatch integration are available. The guard also refuses null/malformed requests and supplied `PASS` or `ALLOW_CAPABILITY` results. A launch without an accounting request retains the existing lifecycle checks; it asserts no financial guarantee.

`alk host-launch preflight --profile <local-launch-profile> --accounting-request <request.json>` refuses before the executable version probe. `alk host-launch accounting-check --profile <accounting-profile.json> --request <request.json> --expectation-digest <sha256> --plan-digest <sha256> --candidate-digest <sha256> [--out <new-file>]` reports exact structural mismatches or unqualified evidence and exits 2. Its output is a refusal diagnostic, never an accepting receipt or dispatch permit. The profile is the closed `alk-accounting-profile.v1` envelope. Final per-adapter profile qualification and current evidence verification remain required.

## Staged source-only qualification

`alk host-launch qualification-check --profiles-root <evidence-root> --adapter <adapter-id> --request <request.json> [--out <new-file>]` checks a staged `profile-payload.json` and `qualification.json` under the adapter directory. It derives bindings from frozen release inputs and current ALK Python sources, verifies archived source bytes and candidate dispositions, and reopens the contents after verifying an actual published ordinary AREA review. Reads share a bounded budget; unsafe or changed inputs refuse. The review must cover the exact `qualification-subject.json` content projection and the adapter obligation. That projection excludes the review reference to avoid a circular review digest.

Only a source-bound `LIFECYCLE_ONLY` profile with no claims can receive `ALLOW_CAPABILITY`. Missing publication, supplied PASS labels, unqualified candidates, native-positive observations and stronger financial requests refuse with exit 2. The result always has `dispatchEntitlement: false`; ALLOW does not accept a final profile, grant launch authority, close finances, authorize retention or emit the final release receipt. The launch guards remain in force. A synthetic test with a provenance double proves join checking, not adapter compatibility or an independently published qualification.

The final validator uses `--profiles-root` without `--preflight`. It requires exact final envelopes, qualification and resolver evidence, published ordinary reviews of both qualification and resolver subjects, reviewed raw counter traces and the existing current-subject core receipt checks. All profiles share a read budget. Failed or unresolved validation writes a `.diagnostic.json` sidecar and leaves the accepting receipt absent. After all21 checks pass, a prepared WS216-02 result is required to emit the DECLARED typed EV216-ACCOUNTING-ENFORCEMENT receipt; ordinary workflow/audit acceptance remains separate. This implementation alone establishes no actual qualified profiles or release readiness.

The resolver trace records the exact missing, stale, forged and replayed qualification inputs as opaque JSON; the producer must execute those inputs, not just label four requests. Each of the nine boundary cases lists its validated predicates or retained core witnesses. Emission rechecks input bytes, ordinary review origins, the original task deadline and the complete current task change-set claim. The 21 profile cases are one DECLARED command witness; the frozen enforcement receipt requires 85 cases across five commands, so this witness alone cannot complete task acceptance.
