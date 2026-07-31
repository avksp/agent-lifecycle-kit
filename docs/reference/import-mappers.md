# Import mappers

Import mappers convert external planning and instruction dialects into ALK
draft artifacts. Imported content is never trusted automatically.

## Supported dialect profiles

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

## Python API

```python
from pathlib import Path

from agent_lifecycle.imports import (
    import_agentskills_dialect,
    import_constitution_adr,
    validate_import_result,
)

result = import_constitution_adr(Path("architecture-decision.md"))
validation = validate_import_result(result)
```

## Safety rules

- External dialect input cannot bypass ALK review.
- Local paths and obvious secret markers block import.
- Resource caps apply before candidate generation.
- Profile digest drift fails validation.
