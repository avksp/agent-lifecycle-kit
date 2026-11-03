# Research workflow

[Русская версия](../ru/guides/research-workflow.md)

Use this workflow when a task needs an architecture study, comparison of
external material, investigation before planning or a review of several
independent sources.

## When to use it

Use a research package when the result must be traceable later or when several
people or models contribute findings. For a short private note, a normal task
file is enough. Research evidence becomes useful when a claim needs a source,
a quote and a clear indication of whether two sources are actually independent.

## Step 1: collect material

Keep the source documents in the operator's working area. Prepare one UTF-8
snapshot per source when exact quote verification is needed:

```text
work/research/
  research-evidence.json
  snapshots/
    source-1.txt
    source-2.txt
```

The portable package stores locators, digests and redaction metadata. It does
not store full documents, prompts, secrets or provider and model names. A host
adapter or an operator-side tool creates the package according to
`agent-research-evidence-package.v1`; ALK validates it but does not fetch the
referenced sites or build a conclusion from a URL.

## Step 2: validate the package

```bash
agent-lifecycle research validate \
  --package work/research/research-evidence.json \
  --snapshot source-1=work/research/snapshots/source-1.txt \
  --snapshot source-2=work/research/snapshots/source-2.txt \
  --out work/research/validation.json
```

Add a `--snapshot SOURCE_ID=PATH` argument only for a source whose quoted range
must be checked locally. A missing snapshot is reported as `UNAVAILABLE` and
creates an evidence gap; it is not silently treated as a verified quote.

## Step 3: read the summary

```bash
agent-lifecycle research summary \
  --package work/research/research-evidence.json \
  --validation work/research/validation.json \
  --out work/research/summary.json
```

Check these fields first:

- `status`: whether the package passed deterministic validation;
- `supportedClaims`: claims with a matched citation and no stale or disputed
  status;
- `evidenceGaps`: claims that still need a source or a verified quote;
- `duplicateGroups`: sources that must not be counted as independent;
- `lifecycleCounts`: the distribution of draft, reviewed, accepted, stale and
  disputed records.

## Step 4: use the result in planning

Treat the summary as reviewed input for a draft specification. Convert useful
claims into explicit requirements, assumptions and acceptance checks. Record
which claims require a test, a code inspection or another domain confirmation.
Then run the normal ALK planning flow:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md --mode plan
agent-lifecycle plan check --manifest <plan-directory>/plan.manifest.json
```

Research validation does not freeze a plan and does not grant implementation
authority. A claim can inform a requirement, but the requirement becomes part
of the lifecycle only after specification review, plan acceptance and freeze.

## Multi-model and multi-source work

Different adapters or models may prepare separate source records or claims.
Keep their outputs separate until provenance and citations are recorded. Review
Mesh can then prepare reviewer packets and synthesize findings. The research
validator checks the evidence package locally; it does not contact any model
or decide which model's conclusion is correct.

## Common cases

| Case | Recommended input | Next ALK step |
| --- | --- | --- |
| Architecture study | Sources, claims, citations and dependency relationships | Draft an architecture section and plan review questions. |
| External project comparison | One source per project, with duplicate and derivative links | Prepare a bounded comparison and mark unsupported claims as gaps. |
| Incident or bug investigation | Reproduction notes, observations and source snapshots | Use the Bug Forensics profile for reproduction and regression proof. |
| Long research before implementation | Periodic reviewed packages with bounded summaries | Attach each summary to the current draft and re-review changed assumptions. |
| Independent review | Separate source records for each reviewer or adapter | Use Review Mesh for assignments, import, synthesis and optional quorum. |

See [research evidence](../reference/research-evidence.md) for the contract,
security rules and complete result semantics.


## Check decisions before task start

Use an optional workstream `decisionResearch` when a task needs a recorded
comparison before execution. It checks the declared frozen inputs. It does not
claim that the selected solution is globally optimal. Tasks without this field
keep their existing behavior.

1. Select a profile at or above the frozen plan tier. S0 requires
   `requirement-fit`; S1 also requires `security`; S2 also requires
   `architecture`, `resources` and `feasibility`. Each required criterion needs
   an assessment and a reason, including when it is not applicable. Add project
   criteria when needed. DORA delivery metrics and scheduling belong to the
   project or external SDLC; they are not a universal ALK policy.
2. Declare the bounded inputs and the record in `planFiles`. Each input must
   also be in the workstream's `contextRefs`. Use unique leaf names in the
   descriptor, with exact raw SHA-256 values. Include `specification.source`
   when present. A whole-workspace or live-input scope is unsupported.
3. Write a record with alternatives, a selected decision, assessments, owner
   and a finite research budget. Include a `NO_CHANGE` alternative. Outcomes
   `KEEP`, `SIMPLIFY` and `REPLACE` can proceed; `SPLIT` and `STOP` require a
   revised reviewed plan. The record has no lifecycle or review authority.
4. Calculate bindings during draft authoring. Use canonical JSON with a final
   newline for JSON files that pass through `freeze-prepare`: its existing
   writer canonicalizes JSON. Hash only after final formatting. Store exactly
   the bytes that you hash; the native guard has no normalization fallback.
5. Prepare the candidate, obtain independent plan review, create the reviewed
   lock and adopt it through the normal lifecycle. Preparation rebases opt-in
   context references into the candidate inventory. Before start, ALK checks
   actual bounded input/record bytes and the adopted independent review.

The core provides deterministic helpers for draft authoring:

```python
from hashlib import sha256
from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.research.preflight import (
    decision_input_digest, decision_policy_digest, decision_scope_digest,
)

policy = workstream["decisionResearch"]
policy["scopeDigest"] = decision_scope_digest(manifest, workstream)
policy["inputDigest"] = decision_input_digest(policy["inputs"])
policy["policyDigest"] = decision_policy_digest(policy)
for key in ("scopeDigest", "inputDigest", "policyDigest"):
    record[key] = policy[key]
record_bytes = canonical_bytes(record) + b"\n"
policy["record"]["sha256"] = sha256(record_bytes).hexdigest()
```

Here `manifest`, `workstream`, `policy` and `record` are complete draft objects.
Write `record_bytes` to the declared record file before review. These helpers
do not create review, a lock or execution permission. Do not edit frozen files
or workflow state to refresh evidence.

The v1 hard ceilings are eight inputs, 65,536 bytes per input, 262,144 record
bytes, three entry points, three alternatives, one probe and two review rounds.
Profiles can lower these limits. A planned budget declares `maxCommands`
(1–100), `maxActiveSeconds` (1–3600) and at least one `reservedCommands`, less
than `maxCommands`. Unknown observed usage uses `UNAVAILABLE` with null
`usedCommands` and `usedActiveSeconds`. `DECLARED` usage remains a report, not
provider telemetry. This check does not meter all host/model calls or tests.

Unchanged bindings and raw bytes can reuse research. A new declared base,
selected task contract, input or profile changes the relevant binding. The
scope excludes physical containers, planned output bytes and unrelated tasks.
Missing, stale, unsafe, over-cap or unsupported evidence refuses before task
start. Direct start and `workflow continue` use the same native guard. A refusal
starts no model research or automatic retry; retain earlier costs and clocks.

The optional generic `evidencePackage` must pass its validator and have actual
snapshots for all declared package sources, with matched citations. A generic
package PASS with unavailable quote evidence is not enough for this preflight.
See [research evidence](../reference/research-evidence.md) for both wire schemas.
