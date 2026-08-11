# Adapter authoring

This guide defines the source-tree contract for adding or updating host
adapters. Adapter code may translate host-local mechanics, but lifecycle
semantics stay in the Agent Lifecycle Kit core.

## Boundary

Adapters own:

- host-local projection metadata;
- host launch and command plumbing;
- event and receipt translation into portable contracts;
- redaction of host-local credential, session and provider details;
- bounded evidence collection for a concrete host version.

Core owns:

- plan, task, audit and workflow state transitions;
- model-route policy and budget enforcement;
- acceptance and final-proof semantics;
- support-level and support-matrix qualification gates.

Unsupported operations must fail closed. A scaffolded adapter is always
`EXPERIMENTAL`; promotion requires live host conformance, usage calibration,
redaction review and support-matrix approval.

## Files

A complete adapter projection should include:

- `adapters/<host>/adapter.descriptor.json`;
- `adapters/<host>/capabilities.manifest.json`;
- host-native projection files, such as plugin or registry metadata;
- fail-closed runner code or host bridge code;
- receipt normalization code that emits `agent-host-operation-receipt.v1`;
- `conformance/adapters/<host>/offline-baseline.json`;
- `docs/adapters/<host>.md`;
- adapter tests that validate descriptor and capability-manifest drift.

The capability manifest is derived from the descriptor and records the
descriptor digest. Do not edit it as a competing source of truth; update the
descriptor, rebuild the manifest, then run validation.

## Commands

```bash
agent-lifecycle adapter scaffold --host <host-id> --target .
agent-lifecycle adapter validate --descriptor adapters/<host-id>/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/<host-id>/adapter.descriptor.json --skip-host-commands
agent-lifecycle adapter install-plan --descriptor adapters/<host-id>/adapter.descriptor.json
agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
```

`adapter install-plan` is a dry run. It previews files, commands and operator
actions for the host projection; host configuration, model launch, support
qualification and production support use their dedicated routes.

For a live host closure, replace `--skip-host-commands` with a bounded safe
inspection profile only after the host binary is installed locally. Inspection
may check host version and help surfaces, but it must not start model work or
claim production promotion.

## Promotion

`VERIFIED` is host-version-specific. Before updating
`docs/adapters/support-matrix.md` or `liveTestedHostRange`, collect:

- passing offline descriptor and capability-manifest validation;
- passing live host conformance receipt;
- passing usage or cost calibration receipt;
- redacted evidence summary under `docs/adapters/evidence/`;
- final lifecycle proof for the release scenario.

If any required host capability is missing, record a qualification decision with
the blocker class and next action. Keep the selected host and evidence scope
explicit when extending a projection.
