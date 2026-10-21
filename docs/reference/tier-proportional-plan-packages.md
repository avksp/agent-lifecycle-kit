# Tier-proportional plan packages

Release 2.23 provides compact authoring for explicit low-risk S0/S1 work. It
creates a canonical DRAFT from caller facts; review, freeze, execution approval
and completion proof remain separate. Existing full S2 packages keep their route.

| Tier | Eligibility | Authoring and review |
| --- | --- | --- |
| S0 | One explicit mechanical change, one executable owner, all risk flags false | Compact source; separate bounded independent review |
| S1 | Up to 12 serial changes, one executable owner, all risk flags false | Compact source; separate standard independent review |
| S2 | Elevated, external, multi-owner or uncertain scope | Existing full package and full independent review; compact input refuses |

Missing tier or required facts refuse; they never imply S0/S1. Architecture,
security, performance, browser, external environment, data, release or external
specification flags require the full S2 route. An explicitly higher S1 tier is
allowed for a mechanical change. Reviewer identities and budgets are never invented.

## Authoring commands

```bash
agent-lifecycle plan package-profiles
agent-lifecycle plan compact-explain --input tasks/compact-example/compact-input.json
agent-lifecycle plan compact-compile \
  --input tasks/compact-example/compact-input.json \
  --out tasks/compact-example/plan.manifest.json
```

Use `--repository-root` when the repository is not the current directory. Profiles
and explain are read-only. An invalid explanation may return `status: FAIL`;
that diagnostic is not an admission. Compilation creates only a new canonical
manifest and refuses an existing output. It starts no model, review, task or
workflow. A generated `planReview.verdict: READY_TO_FREEZE` is a required future
condition, not an actual positive review.

The following is a CONTROLLED example, not an accepted production task. Save it
as the input path above. Replace author, exact base revision, paths, commands,
risk facts and finite caps with the actual project facts before using it.

```json
{
  "schemaVersion": "agent-compact-plan.v1",
  "tier": "S0",
  "mechanical": true,
  "package": {
    "id": "compact-example",
    "title": "Controlled compact authoring example",
    "planArtifactRoot": "tasks/compact-example",
    "artifactRoot": "work/compact-example"
  },
  "author": "fixture-author",
  "baseRevision": {
    "ref": "fixture-source",
    "sha": "1111111111111111111111111111111111111111"
  },
  "owner": "fixture-worker",
  "riskFlags": {
    "architecture": false,
    "security": false,
    "performance": false,
    "browser": false,
    "externalEnvironment": false,
    "data": false,
    "release": false,
    "externalSpecification": false
  },
  "changes": [
    {
      "id": "Import",
      "title": "Repair one missing import",
      "requirement": "Use the standard library module referenced by the worker.",
      "acceptance": "The bounded worker invocation no longer raises a missing-name error.",
      "evidenceDescription": "Controlled regression result, not a production run.",
      "evidencePath": "work/compact-example/import-result.json",
      "writes": [
        "src/example_worker.py"
      ],
      "validationCommands": [
        "python -m unittest tests.test_example_worker -q"
      ]
    }
  ],
  "orchestration": {
    "startMode": "manual-after-freeze",
    "remediationMode": "bounded-auto",
    "maxPlanReviewRounds": 4,
    "maxTaskAttempts": 3,
    "maxParallelTasks": 1,
    "maxValidationRunsPerTask": 4,
    "maxToolCallsPerIteration": 8,
    "maxUsageIterationsPerAttempt": 4,
    "maxToolCallsPerTask": 24,
    "maxToolCallsPerRun": 48,
    "maxReportedTokensPerTask": 4000,
    "maxReportedTokensPerRun": 8000,
    "maxEvidenceArtifactBytes": 65536,
    "maxEvidenceBytesPerTask": 131072,
    "maxEvidenceBytesPerRun": 262144,
    "maxTaskWallSeconds": 600,
    "maxRunWallSeconds": 1200,
    "maxContextBytes": 16384,
    "maxRenderedPacketBytes": 32768
  },
  "releaseImpact": "No publication, migration or release behaviour change.",
  "readOnly": [
    "src/existing_input.py"
  ],
  "forbiddenWrites": [
    ".git",
    ".alk",
    ".claude"
  ],
  "securityGates": [
    "No input, protected path or authority may be overwritten."
  ],
  "contextLimits": {
    "targetReviewerPacketTokens": 4000,
    "maxReviewerPacketTokens": 8000,
    "smallContextProfilesRequired": true
  }
}
```

Source JSON is closed UTF-8, at most 65,536 bytes; canonical output at most
262,144 bytes. Duplicate/unknown keys, nonfinite values, unsafe paths, ambiguous
aliases and hard links refuse. Source/output/review paths must not overlap.
Source must be inside `package.planArtifactRoot`; output must be its
`plan.manifest.json`. Paths and declared authority are checked against the chosen
repository. Stable source checks and identity-bound rollback preserve an existing
or competing output. These are local observed checks and cooperating-writer
coordination, not attested continuous host file protection or a full-host budget.

## Complete the DRAFT before freeze

The compiler inventory initially contains compact source, canonical manifest and
pending independent review. **Before `freeze-prepare`, explicitly author
`acceptance-criteria.md` and add its relative path to the DRAFT `planFiles`.**
The existing freeze consumer requires this checklist; compilation does not
silently generate it. For the example, its table is:

```markdown
| ID | Requirement | Evidence | Criterion |
| --- | --- | --- | --- |
| `AC-Import` | `R-Import` | `EV-Import` | The bounded worker invocation no longer raises a missing-name error. |
```

The added inventory entry is
`tasks/compact-example/acceptance-criteria.md`. Preserve the existing entries,
all AC/requirement/evidence links and caller facts. This is ordinary authoring of
an unreviewed DRAFT; never use it to edit a frozen or accepted plan. An untouched
three-file DRAFT intentionally fails freeze preparation for a missing checklist.

Then use the existing sequence:

1. Run `plan freeze-prepare` with an explicit new candidate directory.
2. Obtain a real independent review of that exact candidate and its complete
   declared inputs. The reviewer must actually differ from the author/worker.
3. Run `plan lock-create` with that current accepting report and verify the lock.
4. Compile worker packets and follow ordinary workflow initialization, plan
   adoption and separate execution authorization.
5. Preserve task reviews, final audit, accounting and applicable release gates.

Legacy v1 review validation relies on the declared `independent: true` flag;
it does not establish actual reviewer identity or host-attested independence.
A declaration cannot substitute for the real separate reviewer. Compact authoring
adds no stronger provenance claim or automatic approval.

## Mapping and evidence boundaries

A change id X maps to R-X, AC-X, EV-X and WS-X. Explicit requirements, acceptance,
evidence path/description, literal writes, serial dependencies and all caps remain.
Per-change commands are preserved in `workstreams[].plannedItems[].validationCommands`;
the global command inventory is their stable union. Commands are recorded, not run.

Compact v1 describes ordinary evidence only. It does not place a commands-only
dictionary in reserved `acceptance.evidence[].validation`. Typed producer/subject
or provenance requirements need the full S2 route; unknown guarantee fields refuse
rather than being dropped. Existing typed evidence validators remain unchanged.

## Controlled comparison and limits

Two explicitly authored compact/verbose fixtures preserve all canonical facts
except listed source-document locations. The common checklist and its inventory
preparation count on both sides. These are controlled structural observations,
not real 2.21 sessions or representative production workflows.

| Case | Verbose authoring + checklist | Compact authoring + checklist | Files on each side |
| --- | ---: | ---: | ---: |
| Controlled S0 | 5,308 bytes | 2,539 bytes | 2 |
| Controlled S1 | 6,931 bytes | 3,190 bytes | 2 |

Generated canonical sizes were equal for each pair. Review input bytes were
measured separately. Three alternating local structural repetitions per pair
showed slightly more local work for compact compilation than canonical validation
alone; sub-millisecond samples do not establish full-workflow speed. Publication
I/O was checked separately; unchanged compilation boundaries retain their source pins.

Real authoring labor, model input/output/cache tokens, active model time, USD and
full-cycle savings are `UNAVAILABLE`, not zero. Byte deltas alone do not establish
model savings. An unsafe acceptance, lost fact, weaker assurance or full S2
regression blocks promotion. Missing real economics alone does not disable the
feature; quality and authority checks remain mandatory.

See [plan completeness](plan-completeness.md), [CLI](cli.md),
[authority boundaries](authority-artifact-boundaries.md) and
[workflow continuation](workflow-continuation.md).
