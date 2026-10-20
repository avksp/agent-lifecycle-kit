# Safe artifact authoring

ALK 2.19 adds create-only JSON helpers and a read-only planning preflight.
They reuse the existing validators, reviewed lock, workflow and evidence gates.
Creating valid JSON does not make its claims true or authorize execution.

## Create and inspect

```bash
agent-lifecycle task artifact-create --kind json --input advisory.json --out new/advisory.json
agent-lifecycle task artifact-inspect --input new/advisory.json --max-display-bytes 8192
```

`--input` contains one structured JSON object; pretty input is accepted here.
The output is canonical JSON, exclusively created without replacing an existing
file. Duplicate members, nonfinite numbers, excessive size/depth, unsafe parents,
symlinks, collisions and sensitive content refuse. The whole structured request
is limited to 262144 bytes. Authoritative readers keep their strict contracts.

| Kind | Context | Meaning |
| --- | --- | --- |
| `json` | Structured object. | Serialization only; `authoritative: false`. |
| `task-result` | `--state`, `--task`, current task lineage, worker identity and native change-set claim. | Uses the existing task-result validator. Commit, independent review and acceptance are separate. |
| `evidence` | Existing closed `agent-evidence-receipt.v1` payload. | Computes and checks the existing digests; shape alone does not attest a command or accept a task. |

Typed task example:

```bash
agent-lifecycle task artifact-create --kind task-result --state work/run.state.json --task WS-01 --input result-input.json --out work/new-task-result.json
```

The caller supplies actual observations and identities. ALK neither invents a
worker nor converts command stdout into a successful receipt. FAIL, SKIPPED,
findings and unknown usage remain meaningful. Unknown telemetry is null, never
zero. Local actor identities and command arguments are preserved in bound data;
credentials are rejected. `--redact-advisory` is available only for generic
advisory JSON with `authorityClaimed: false` and explicitly keeps authority false; it cannot repair a typed
identity by redacting and claiming the original digest.

`artifact-inspect` does not create an alternative pretty authority file. It
returns the original path and canonical digest plus a redacted bounded display
and truncation metadata. Display limits are 256–65536 bytes. Redaction or a
truncated display is not the original artifact; use its retained identity when
checking evidence.

## Prepare a freeze candidate

```bash
agent-lifecycle plan freeze-prepare --manifest plans/draft/plan.manifest.json --out candidates/review-01 --repository-root .
```

The input must be a valid DRAFT package. ALK runs the existing planning preflight
and output-footprint guard, inventories the declared package and creates a new
candidate. At most 64 input files and 8 MiB aggregate input are accepted. JSON is
canonicalized; other declared bytes are preserved. Only declared package paths
are relocated. Input files and old locks remain unchanged.

The candidate contains proposed FROZEN metadata, a reserved independent review
path and a preparation receipt. It contains no accepting review, lock or
execution permission. Missing inputs, traversal, aliases, oversized content and
output overlap with input or frozen authority refuse before directory creation.
A new output root is required; concurrent writers cannot replace the winner.

“Immutable candidate” means create-only bytes plus digest-based drift detection.
It does not mean OS-enforced protection against the file owner. Review the exact
candidate, then use the existing `plan lock-create`, `plan verify`, task compile,
adoption and separate authorization commands. Later edits need a new candidate
and review. Do not manufacture a positive review to demonstrate the sequence.

## Read-only planning guidance

```bash
agent-lifecycle plan verify --manifest candidates/review-01/plan.manifest.json --repository-root . --out work/verification.json --compact
```

`plan verify` is the primary structural preflight. Its full typed receipt binds
the manifest and reports named checks, stable blocker codes and bounded context,
including missing package/lock, traceability, ownership or output conflicts.
Choose the repair from that check's details, then prepare a new candidate if its
authority changes. For example, `plan-lock-required` on an unreviewed candidate
requires genuine review and lock creation; it is not a suggestion to fabricate
the missing lock. Semantic audit remains required by the selected SDD tier.

`--compact` requires `--out` so the full receipt remains available by path and
digest. The default output is unchanged. Guidance executes no shell repairs,
does not authorize work and does not introduce another `workflow nextAction`.
Do not repeatedly run successful checks unless changed dependencies invalidate
them. Preserve spent resources and valid results after a timeout or overrun.

## Discover hot-path schemas

```bash
agent-lifecycle schema list --scope core
agent-lifecycle schema show agent-artifact-authoring-request.v1
```

The small core view identifies the actual contextual validators for authoring,
closed evidence receipts, accepting plan reviews and prepared raw reviewer
outputs. `schema list` still returns the complete legacy registry; `schema show`
keeps its existing interface. A descriptive schema is not execution authority.
Cross-file identity, source freshness, independent judgement and acceptance
still require their named runtime consumers and context.

## Prepare reviewer inputs

Use [Review Mesh](review-mesh.md#bounded-review-handoff) for the optional portable
reading index and raw response contract. Preparation verifies local inputs and
creates packets without launching reviewers or proving delivery. Keep raw
`reviewer-output.v1` separate from normalized `agent-review-mesh-result.v1`.

See [the SDLC boundary](../architecture/sdlc-boundary.md) for the distinct roles
of ALK, the host, model, repository and independent reviewer.
