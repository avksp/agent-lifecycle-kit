# Import mappers

Import mappers переводят внешние planning/instruction dialects в draft
артефакты ALK. Импортированный контент никогда не считается доверенным
автоматически.

## Поддерживаемые dialect profiles

- `external-workflow-generic`: generic workflow-like YAML или JSON со step/job/
  check hints.
- `external-agent-generic`: generic agent/harness-like YAML или JSON с role,
  policy, tool и env hints.
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

Generic external imports добавляют family/profile слой перед созданием draft:

```text
parse -> normalize -> sanitize/redact -> draft artifact -> validate -> review/freeze
```

Workflow-family imports переводят steps/jobs/checks в draft requirements, work
hints и validation hints. Это контекст для review; ALK не выполняет импортированные
workflow nodes.

Agent-family imports переводят role/policy hints в draft requirements. Provider,
model, auth, environment и tool hints считаются host-local metadata. Значения
redacted или представлены digest и не могут стать portable defaults.

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

- Внешний dialect input не может обойти ALK review.
- Локальные пути и явные secret markers блокируют импорт.
- Resource caps применяются до генерации candidate plan.
- Drift `profileDigest` приводит к FAIL.
- Импортированные workflow nodes никогда не выполняются.
- Provider, model, auth, environment и tool hints из agent-family inputs
  остаются host-local и не становятся portable core defaults.
