# Import mappers

Import mappers переводят внешние planning/instruction dialects в draft
артефакты ALK. Импортированный контент никогда не считается доверенным
автоматически.

## Поддерживаемые dialect profiles

- `constitution-adr`: документы в стиле Constitution или ADR с principles,
  constraints, decisions и numbered requirements.
- `agents-agentskills`: файлы `AGENTS.md` или инструкции в стиле agentskills.

Каждый профиль использует `agent-import-dialect-profile.v1` и фиксирует:

- `dialectId` и `dialectKind`;
- `sourceTrusted: false`;
- `requiresReview: true`;
- `freezeBlocked: true`;
- `profileDigest`.

## Поведение импорта

Dialect imports используют тот же untrusted planning import path, что и
обычный импорт. Результат `agent-planning-import-result.v1` содержит
`nativeDialectProfileDigest`, а candidate plan записывает этот же digest в
`candidatePlan.importState.nativeDialectProfileDigest`.

Candidate plan остаётся `DRAFT` с обязательными review, audit и freeze gates.
Перед реализацией оператор должен пройти обычный ALK review и freeze.

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

- Внешний dialect input не может обойти ALK review.
- Локальные пути и явные secret markers блокируют импорт.
- Resource caps применяются до генерации candidate plan.
- Drift `profileDigest` приводит к FAIL.
