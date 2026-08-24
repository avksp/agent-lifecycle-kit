# Structured result qualification

Release 1.89 adds a provider-neutral contract for checking whether an execution
setup can produce structured results for one ALK operation. It is an optional
qualification surface. It does not replace the frozen plan, task-result
acceptance, implementation review or final workflow proof.

## Capability is operation-bound

ALK records a capability claim only for the operation being evaluated. The
claim is bound to all of these values:

- operation identifier;
- adapter identity and descriptor digest;
- host version and model class;
- capability-manifest digest;
- required output schema;
- plan and lock lineage.

The public contract is `agent-structured-result-capability.v1`. A changed,
missing, stale or replayed binding returns `UNAVAILABLE` or `FAIL`. It never
raises a weaker observation to a stronger capability level. The levels are
`SCHEMA_ENFORCED`, `JSON_ENFORCED`, `VALIDATED_TEXT` and `UNAVAILABLE`.

The capability declaration is evidence about a route, not permission to use
that route. It cannot accept a workflow task, authorize an action, change a
security gate or claim production promotion.

## Select without silent downgrade

Selection uses `agent-structured-result-selection.v1`. ALK chooses the
strongest qualified mode that satisfies the required schema and records the
required schema and plan/lock lineage. If schema enforcement is required but
unavailable, selection fails closed. It does not silently switch to a weaker
mode just to obtain a result.

The selection boundary is intentionally separate from any host command. A
host adapter may provide a capability manifest, but ALK validates its lineage
against the adapter descriptor before treating the declaration as evidence.

## Validate and repair boundedly

`agent-structured-result-validation.v1` describes deterministic validation of
the returned envelope. It rejects malformed JSON, missing required fields,
wrong schemas, stale lineage and replayed receipts. Structured-result repair
has a fixed maximum of two attempts. Lifecycle task attempts are a separate
budget, controlled by the frozen `maxTaskAttempts` value, and are not increased
by structured-result repair.

An exhausted repair budget cannot become accepted evidence. Repair cannot
change the required schema, quality criteria, security gates or plan lineage.

## Qualification evidence

The qualification report uses the existing reference-task evidence model. A
route must contain all of the following before it can receive a technical
qualification recommendation:

- at least five distinct reference tasks;
- two completed runs for every task;
- at least five distinct `family/tier/shape` strata;
- two completed runs for every stratum;
- positive, boundary and malformed-output fixtures;
- complete lineage and structured-result measurements for every run.

Missing evidence or a failed negative fixture produces `NO_RECOMMENDATION`.
One successful run is never sufficient. The report remains advisory and has
`automaticRouteAdoptionEligible: false` and `advisoryOnly: true`; it cannot
accept a task or change an adapter's support level.

For the existing deterministic suite, the route evidence can be checked with
the regular benchmark commands:

```bash
agent-lifecycle benchmark qualify \
  --suite benchmarks/reference-tasks/manifest.json \
  --sample work/benchmark/sample.json \
  --receipt work/benchmark/run-01.json \
  --receipt work/benchmark/run-02.json \
  --out work/benchmark/qualification.json
```

This command reads external execution records. It does not start a model or
host process. The structured-result qualification helpers and receipts are
also available through the Python API; Release 1.89 intentionally does not
invent a provider-specific CLI switch for response formatting.

## Contract and authority boundaries

The relevant schemas are:

- `agent-structured-result-capability.v1`;
- `agent-structured-result-selection.v1`;
- `agent-structured-result-output-contract.v1`;
- `agent-structured-result-validation.v1`;
- `agent-structured-result-measurement.v1`;
- `agent-workflow-structured-result-artifact.v1`.

The generic output contract is shared with small-model packet compilation. It
is not a second compiler authority or a second workflow engine. A structured
result artifact is advisory until the ordinary ALK task-result, ownership,
freshness, review and finalization checks accept the work.

The capability level is therefore useful for comparison and diagnosis, while
the frozen plan and lifecycle state remain the source of authority.
