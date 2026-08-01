# Import mappers

Import mappers convert external planning and instruction dialects into ALK
draft artifacts. Imported content is never trusted automatically.

## Supported dialect profiles

- `external-workflow-generic`: generic workflow-like YAML or JSON with
  step/job/check hints.
- `external-agent-generic`: generic agent/harness-like YAML or JSON with
  role/policy/tool/env hints.
- `constitution-adr`: Constitution or ADR-style documents with principles,
  constraints, decisions and numbered requirements.
- `agents-agentskills`: `AGENTS.md` or agentskills-style instruction files.

Each profile uses `agent-import-dialect-profile.v1` and records:

- `dialectId` and `dialectKind`;
- `sourceTrusted: false`;
- `requiresReview: true`;
- `freezeBlocked: true`;
- `profileDigest`.

## Import behavior

Dialect imports call the same untrusted planning import path as generic imports.
The resulting `agent-planning-import-result.v1` includes
`nativeDialectProfileDigest`, and the candidate plan records the same digest in
`candidatePlan.importState.nativeDialectProfileDigest`.

The candidate plan remains `DRAFT` with review, audit and freeze blockers. The
operator must run normal ALK plan review and freeze before implementation.

Generic external imports add a family/profile layer before draft creation:

```text
parse -> normalize -> sanitize/redact -> draft artifact -> validate -> review/freeze
```

Workflow-family imports map steps/jobs/checks to draft requirements, work hints
and validation hints. The hints are context for review; ALK never executes
imported workflow nodes.

Agent-family imports map role and policy hints to draft requirements. Provider,
model, auth, environment and tool hints are host-local metadata. Their values
are redacted or represented by digests and cannot become portable defaults.

```bash
agent-lifecycle import profile-list
agent-lifecycle import external --family workflow --source workflow.yaml --out import.json
agent-lifecycle import external --family agent --source agent.yaml --out import.json
agent-lifecycle import external-check --candidate import.json
```

## Python API

```python
from pathlib import Path

from agent_lifecycle.imports import (
    import_external_agent,
    import_external_workflow,
    import_agentskills_dialect,
    import_constitution_adr,
    validate_import_result,
)

result = import_constitution_adr(Path("architecture-decision.md"))
workflow_result = import_external_workflow(Path("workflow.yaml"))
agent_result = import_external_agent(Path("agent.yaml"))
validation = validate_import_result(result)
```

## Safety rules

- External dialect input cannot bypass ALK review.
- Local paths and obvious secret markers block import.
- Resource caps apply before candidate generation.
- Profile digest drift fails validation.
- Imported workflow nodes are never executed.
- Provider, model, auth, environment and tool hints from agent-family inputs
  stay host-local and cannot become portable core defaults.
