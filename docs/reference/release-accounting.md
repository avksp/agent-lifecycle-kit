# Release accounting

Release accounting converts explicit local evidence into one deterministic,
validated `agent-release-accounting.v1` artifact. It is an observability
boundary, not a billing system and not workflow authority. The command starts
no model, host process or network call and never infers unavailable usage.

## Build phase measurements

Prepare an `agent-phase-resource-input.v1` object:

```json
{
  "schemaVersion": "agent-phase-resource-input.v1",
  "phases": [
    {
      "phaseId": "implementation",
      "phaseKind": "IMPLEMENTATION",
      "taskId": "WS-01",
      "operationId": "ws-01-result",
      "tokens": {"input": 700, "output": 300, "total": 1000},
      "steps": 7,
      "resources": {"toolCalls": 12, "validationRuns": 3},
      "durationMs": 420000,
      "receiptDigests": []
    }
  ],
  "lineage": {"runId": "release-run-1", "sourceRevision": "abc123"},
  "sourceArtifacts": []
}
```

Generate the canonical measurement:

The result uses schema `agent-phase-resource-measurement.v1`.

```bash
agent-lifecycle metrics phase-resources \
  --input work/phase-resource-input.json \
  --out work/phase-resources.json
```

The input is limited to 1 MiB and 256 phases. Output uses create-only
semantics. Tokens, steps, duration and resource counters must be non-negative
integers; monetary fields and unsupported resource names are rejected.

## Compose release accounting

The accounting command accepts one or more phase measurements or
`agent-release-accounting-source.v1` artifacts contained by `--project-root`:

```bash
agent-lifecycle metrics release-accounting \
  --release-id 2.6.0 \
  --project-root . \
  --artifact work/phase-resources.json \
  --artifact work/external-audit-accounting.json \
  --provenance work/release-provenance.json \
  --out work/release-accounting.json
```

At most 64 unique source artifacts and 1024 aggregate entries are accepted.
Files are read through the stable repository-file boundary with a 1 MiB limit
per artifact. Paths outside the project, symlinks, repeated byte content and
repeated canonical payloads fail closed. The output is canonical, validated
before the generation receipt is returned, and never replaces an existing
file.

## Views and metrics

Every result contains four fixed views:

- `alkProcess`: planning and lifecycle coordination;
- `implementation`: product implementation;
- `audit`: independent and product validation;
- `postAuditRemediation`: fixes caused by audit findings.

Each view reports `tokens`, `steps`, `elapsedWallMs` and `computeMs` separately.
`elapsedWallMs` is elapsed time; `computeMs` can sum parallel reviewer compute
and must not be added to wall time. Missing telemetry is represented as
`{"status":"UNAVAILABLE","value":null}` rather than zero. Mixed and partial
inputs retain `MIXED` or `PARTIAL` status.

Only entries whose scope has `additive: true` contribute to totals. A snapshot
covering several releases must be non-additive; it remains visible in
`exclusions` with reason `NON_ADDITIVE_SCOPE`. Consumers must read metric
status and exclusions, not only numeric values.

## Provenance

The optional provenance file may declare these identities independently:

- `controllerVersion` and `coreVersion`;
- `hostPluginVersion` and `skillPackageVersion`;
- `runAlkVersion`, `runId` and `sourceRevision`;
- `measurementDigest`.

Observed and declared values remain separate. A disagreement is `MISMATCH`,
not evidence of freshness, and never becomes `ATTESTED`. Source descriptors,
identity status, totals and exclusions are covered by `accountingDigest`.

## Existing cost report

`metrics cost-report` accepts a phase-resource measurement as an artifact. For
that schema it uses declared token and step totals rather than estimating
tokens from serialized JSON size:

```bash
agent-lifecycle metrics cost-report \
  --artifact work/phase-resources.json \
  --project-root . \
  --mode release \
  --out work/cost-report.json
```

Release accounting is advisory evidence. It cannot accept a task, authorize
execution, lower a quality gate or claim production promotion.
