# Modular Controller Architecture

## Decision

The standalone release shall not ship a production controller implemented as
one large `workflowctl.py` script. Historical monolithic scripts may be used
only as migration references or bootstrap shims. The release implementation
must provide a modular Python package with a thin CLI facade.

The stable external contract may remain the same: command names, compact JSON
outputs, exit codes, run state, WAL records, task packets, receipts and final
proof identities stay compatible unless a schema migration is explicitly
frozen. What changes is code ownership and context shape.

## Required Boundaries

- `contracts`: dataclasses, enums, schema loading and canonical JSON.
- `ports`: filesystem, process, clock, crypto, adapter and usage interfaces.
- `state`: run state, WAL, migrations, locking and crash recovery.
- `operation_kernel`: operation ids, preconditions, output descriptors and
  atomic publication.
- `planning`: clarification, SDD tiering, specification and plan lifecycle.
- `compilation`: frozen DAG validation and task packet generation.
- `authorization`: execution approval, capability checks and fail-closed
  policy.
- `task_runtime`: launch, wait, cancel, reconcile and result ingestion.
- `validation`: controller gates, command receipts and evidence freshness.
- `audit`: task/final review normalization and verdict transitions.
- `release`: matrix, assembly, neutrality release and generation verification.
- `terminal`: final-audit handoff, finalization neutrality and final proof.
- `adapters`: host-operation protocol projections only.
- `api`: compact controller service functions.
- `cli`: argument parsing and response formatting only.

Dependency direction is one-way:

```text
cli -> api -> use-case modules -> contracts/ports
adapters -> host protocol contracts
core modules do not import adapters
```

## Size And Small-Context Gates

These limits are release gates for Python source files:

- target maximum source file length: 800 logical lines;
- hard maximum source file length: 1200 logical lines;
- target maximum function length: 80 logical lines;
- hard maximum function length: 150 logical lines;
- top-level CLI dispatcher hard maximum: 500 logical lines;
- external shell launcher hard maximum: 24 logical lines;
- target maximum top-level symbols per module: 40;
- hard maximum top-level symbols per module: 80.

Any exception must be justified by generated code or schema data and excluded
from semantic runtime modules. The conformance suite shall include a context
shape report proving that each controller module can be reviewed in isolation
with its directly owned tests and contracts.

## SOLID, DRY And YAGNI Policy

SOLID is required where it creates testable lifecycle seams: state transition,
artifact store, operation publication, host adapter, usage attestation,
authorization gate and validator execution. It is not a reason to add deep
inheritance, speculative factories or framework-heavy dependency injection.

DRY applies to canonical JSON serialization, digest calculation, WAL append,
operation publication, receipt verification, path confinement and adapter
capability declarations. Similar-looking logic across different trust domains
must stay separate when collapsing it would weaken auditability.

YAGNI blocks unrequested surfaces and infrastructure. The release keeps five
canonical lifecycle skills, no hosted control plane, no mandatory MCP/app
server, no provider-specific model routing in core contracts, no copied
project samples, and no live-adapter promotion as a production prerequisite.
