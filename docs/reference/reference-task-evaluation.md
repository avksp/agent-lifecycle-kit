# Reference task evaluation

`agent-lifecycle benchmark evaluate` compares supplied ALK artifacts with a
versioned, deterministic task oracle. It is a read-only local command: it does
not call a model, start an adapter host, change workflow state, or decide that a
real project is production-ready.

## Command

```bash
agent-lifecycle benchmark evaluate \
  --suite benchmarks/reference-tasks/manifest.json \
  --artifact work/benchmark/submission.json \
  --out work/benchmark/evaluation.json
```

The command prints and optionally writes
`agent-reference-task-evaluation.v1`. Output files are write-once.

## Submission

The input uses `agent-reference-task-submission.v1`:

```json
{
  "schemaVersion": "agent-reference-task-submission.v1",
  "taskId": "rt01-planning",
  "taskVersion": "1.0.0",
  "accepted": true,
  "evidence": {
    "planValidation": {"schemaVersion": "agent-plan-validation.v1", "status": "FROZEN"},
    "completenessValidation": {"schemaVersion": "agent-plan-completeness-validation.v1", "status": "PASS", "blockers": []},
    "acceptanceValidation": {"schemaVersion": "agent-acceptance-checklist-validation.v1", "status": "PASS", "missingInMarkdown": [], "extraInMarkdown": [], "linkMismatches": []}
  },
  "productionPromotionClaimed": false
}
```

Add an existing `agent-usage-export.v1` under `evidence.usageExport` to measure
tokens and elapsed time. Add an existing `agent-task-outcome-index.v1` under
`evidence.outcomeIndex` to measure retries. The evaluator consumes these
receipts; it does not recreate their authority.

Submission evidence is bounded to 64 nested container levels and 100,000
values. Inputs exceeding either limit fail through the typed ALK error path
before oracle evaluation or digest generation.

## Oracle families

| Task | Deterministic pass condition |
| --- | --- |
| `rt01-planning` | Frozen plan, passing completeness receipt, and acceptance crosswalk with no mismatch. |
| `rt02-architecture-review` | Passing Review Mesh quorum with required roles, resolved blocking findings, and no blocker. |
| `rt03-bug-forensics` | Passing reproduction and regression-proof chain with matching digests. |
| `rt04-s1-managed-task` | Complete task result, passing commands, and independent implementation audit accepted. |
| `rt05-s2-evidence-task` | Ready final proof, passing final implementation/proof-integrity validations, and any opted-in quorum satisfied. |

The oracle reads only typed artifacts produced outside the evaluator. It does
not inspect prompts or ask the result-producing model to score itself.

## Measurements

The receipt reports:

- passed and total deterministic criteria;
- token buckets for `ATTESTED`, `ESTIMATED`, and `MISSING` evidence;
- elapsed milliseconds from usage-export entries;
- retries from the task outcome index;
- explicit measurement gaps.

When token confidence is mixed, `tokens.headline.total` is `null`. Consumers
must use the separate buckets and must not combine attested and estimated data
into an unlabeled total.

## False acceptance

If `accepted` is `true` while the oracle fails, the evaluation receipt has:

```json
{"status":"FAIL","summary":{"falseAcceptanceCount":1}}
```

The CLI still exits successfully because it produced a valid negative
evaluation. Automation must inspect the receipt status and count. Command or
input errors use the normal ALK error path instead.

## Security and scope

Results store digests, byte counts, typed checks, measurements, and redacted
summaries. Raw task/chat transcripts are not copied. Shared redaction removes
common credentials and private local paths. `evaluationDigest` covers the
redacted receipt body, including its redaction status, rather than the supplied
raw evidence. A synthetic result cannot satisfy production evidence, adapter
maturity, or promotion requirements.

It does not call a model. It cannot satisfy production evidence.
