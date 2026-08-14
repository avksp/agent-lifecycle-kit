# Evaluate an external model harness

[Русская версия](../ru/guides/model-harness-evaluation.md)

Use this guide when the model or host harness is operated outside ALK and you
want a repeatable quality and resource comparison. The harness performs the
task and writes an execution record with sensitive data removed, using schema
`agent-benchmark-run-receipt.v1`; ALK validates and compares the records.

Here, an execution setup means the neutral combination of an adapter, model
class, environment and scorer used for the same task set. The schema keeps the
technical field name `receipt` for compatibility.

1. Create a deterministic sample with `agent-lifecycle benchmark sample`.
2. Run the same task pool through each execution setup.
3. Keep the task, environment and scorer digests in every execution record.
4. Check every execution record with `agent-lifecycle benchmark receipt-check`.
5. Validate each setup with `agent-lifecycle benchmark qualify`.
6. Compare only setups whose reports have the technical status `QUALIFIED` using
   `agent-lifecycle benchmark compare-routes`.

Quality evidence is mandatory before any token or time conclusion. The minimum
coverage is five tasks, two completed runs per task, five family/tier/shape
strata and two runs per stratum. Missing quality or mixed attestation produces
`NO_RECOMMENDATION` or `INCOMPARABLE`.

The external harness may use a hosted, small or local model. It owns model
selection and process execution; ALK does not call a provider, launch a host or
make an automatic choice of execution setup.
