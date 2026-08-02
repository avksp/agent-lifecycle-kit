# Импорт внешних форматов

Импорт внешних форматов переводит сторонние форматы планирования и инструкций в
черновые артефакты ALK. Импортированный контент никогда не считается доверенным
автоматически.

## Поддерживаемые профили форматов

- `external-workflow-generic`: YAML или JSON, похожий на рабочий процесс, с
  подсказками по шагам, задачам и проверкам.
- `external-agent-generic`: YAML или JSON, похожий на конфигурацию агента или
  запуска, с подсказками по роли, правилам, инструментам и окружению.
- `constitution-adr`: документы в стиле Constitution или ADR с принципами,
  ограничениями, решениями и нумерованными требованиями.
- `agents-agentskills`: файлы `AGENTS.md` или инструкции в стиле agentskills.

Каждый профиль использует `agent-import-dialect-profile.v1` и фиксирует:

- `dialectId` и `dialectKind`;
- `sourceTrusted: false`;
- `requiresReview: true`;
- `freezeBlocked: true`;
- `profileDigest`.

## Поведение импорта

Импорт форматов использует тот же недоверенный путь импорта плана, что и
обычный импорт. Результат `agent-planning-import-result.v1` содержит
`nativeDialectProfileDigest`, а план-кандидат записывает этот же отпечаток в
`candidatePlan.importState.nativeDialectProfileDigest`.

План-кандидат остаётся `DRAFT` с обязательными проверками, аудитом и
заморозкой. Перед реализацией оператор должен пройти обычные этапы проверки и
заморозки ALK.

Общий импорт внешних данных добавляет слой семейства и профиля перед созданием
черновика:

```text
parse -> normalize -> sanitize/redact -> draft artifact -> validate -> review/freeze
```

Импорт семейства workflow переводит шаги, задачи и проверки в черновые
требования, рабочие подсказки и подсказки для проверки. Это контекст для
проверки; ALK не выполняет импортированные узлы workflow.

Импорт семейства agent переводит подсказки по роли и правилам в черновые
требования. Подсказки `provider`, `model`, `auth`, `environment` и `tool`
считаются локальными метаданными хоста. Значения маскируются или представлены
отпечатком и не могут стать переносимыми настройками по умолчанию.

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

## Правила безопасности

- Внешний входной формат не может обойти проверку ALK.
- Локальные пути и явные признаки секретов блокируют импорт.
- Ограничения ресурсов применяются до генерации плана-кандидата.
- Изменение `profileDigest` приводит к `FAIL`.
- Импортированные узлы workflow никогда не выполняются.
- Подсказки `provider`, `model`, `auth`, `environment` и `tool` из входных
  данных семейства agent остаются локальными для хоста и не становятся
  переносимыми настройками ядра.
