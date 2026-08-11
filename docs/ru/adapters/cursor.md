# Адаптер Cursor

Проекция Cursor содержит общие навыки жизненного цикла, корневой
`.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json` и манифест
возможностей `adapters/cursor/capabilities.manifest.json`.

Текущий статус: `EXPERIMENTAL`. Локальный безопасный осмотр Cursor Agent
`2026.07.23-e383d2b` прошёл, но для `VERIFIED` не хватает принятых
подтверждений реального запуска, калибровки расхода и финального подтверждения
жизненного цикла.

Локальная проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/cursor/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/cursor/adapter.descriptor.json \
  --skip-host-commands

python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host cursor \
  --evidence <adapter-conformance-evidence.json>
```

Публичная публикация Cursor требует отдельной проверки Cursor Marketplace.
Текущая причина блокировки: локальная Free-подписка не заменяет подтверждение
расхода и финальное подтверждение. Прямой безопасный запуск CLI хоста из ядра не
заявляется.

## Запуск только для планирования

Точная версия профиля: `2026.07.23`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Внешний инструмент пока не имеет подтверждённой ограниченной передачи результата через стандартный ввод.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter cursor --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/cursor.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/cursor.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/cursor.json
```

Успешная проверка версии не разрешает запуск планирования.
`managedLaunch.status` остаётся `WRAPPER_ONLY`, а зрелость адаптера не повышает
состояние поддержки планирования. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в Cursor

Подключите доверенный каталог к локальному каталогу модулей Cursor,
перезагрузите приложение, откройте целевой проект и укажите: `Используй навык
agent-workflow-orchestrator для этой задачи: <задача>`. Этот способ не меняет
состояние адаптера `EXPERIMENTAL`.

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит
результатов реализации и принятое итоговое доказательство.
Задача: <опиши задачу или укажи Markdown-файл>
```

Запуск через команду:

```bash
agent-lifecycle start --adapter cursor --file task.md
```

Команда создаёт черновые входные артефакты и по умолчанию не запускает Cursor.
Подробнее: [использование ALK с адаптером](usage-modes.md).
