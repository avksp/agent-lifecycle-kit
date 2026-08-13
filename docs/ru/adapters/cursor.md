# Адаптер Cursor

Проекция Cursor содержит общие навыки жизненного цикла, корневой
`.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json` и манифест
возможностей `adapters/cursor/capabilities.manifest.json`.

Текущий уровень поддержки: `EXPERIMENTAL`. Cursor Agent
`2026.07.23-e383d2b` прошёл локальный осмотр; следующий этап квалификации —
реальный запуск с подтверждением расхода, ресурсов и жизненного цикла.

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
В матрице поддержки текущая причина обозначена как
`BLOCKED_FREE_SUBSCRIPTION_PROMOTION_EVIDENCE`; для продолжения квалификации
нужно получить подтверждение расхода, ресурсов и жизненного цикла на подходящем
диапазоне хоста.

## Запуск только для планирования

Точная версия профиля: `2026.07.23`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Профиль содержит
квалификационный маршрут для ограниченной передачи результата через стандартный
ввод и подтверждения изолированного запуска.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter cursor --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/cursor.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/cursor.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/cursor.json
```

Допустимость запуска планирования определяется статусом профиля и матрицей
поддержки. `managedLaunch.status` имеет значение `WRAPPER_ONLY`; порядок
квалификации описан в разделе [запуска адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в Cursor

Подключите доверенный каталог к локальному каталогу модулей Cursor,
перезагрузите приложение, откройте целевой проект и укажите: `Используй навык
agent-workflow-orchestrator для этой задачи: <задача>`. Этот способ использует
уровень поддержки, указанный для Cursor.

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

Команда создаёт входные артефакты ALK. Для запуска Cursor добавьте проверенный
профиль и `--launch`.
Подробнее: [использование ALK с адаптером](usage-modes.md).
