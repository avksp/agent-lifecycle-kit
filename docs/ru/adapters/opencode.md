# Адаптер OpenCode

Проекция OpenCode содержит общие навыки жизненного цикла, корневой
`opencode.json`, JS-проекцию под `adapters/opencode/` и манифест возможностей.
Код OpenCode не должен повторно реализовывать планирование, фиксацию плана,
рабочий цикл, проверку или финальный аудит.

Текущий статус: `VERIFIED` для OpenCode CLI `1.18.9`. Это не публикация в npm,
не одобрение публичного каталога и не поддержка непроверенных версий.

Локальная установка зависит от конфигурации OpenCode: скопируйте `skills/*` в
`.opencode/skills/` или `~/.config/opencode/skills/`, а
`adapters/opencode/plugins/agent-lifecycle-kit.js` — в соответствующий каталог
`.opencode/plugins/`.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/opencode/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/opencode/adapter.descriptor.json \
  --skip-host-commands
```

Резюме осмотра: `docs/adapters/evidence/opencode-0.7.0.md`.
Резюме реального запуска: `docs/adapters/evidence/opencode-host-local-live-2026-07-29.md`.
Провайдер, модель, прямой запуск и телеметрия остаются на стороне хоста.

## Квалифицированный локальный запуск

Для OpenCode `1.18.15` предусмотрен отдельный локальный профиль с точной
привязкой к версии. Он не использует `--auto`, не меняет полное подтверждение
адаптера для версии `1.18.9` и не подтверждает учёт токенов для S1/S2. См.
[квалифицированный запуск внешнего
инструмента](../reference/qualified-host-launch.md).

Маршрут только для планирования явно имеет статус
`PLANNING_ONLY_UNSUPPORTED`, пока не появятся безопасный профиль внешнего CLI и
подтверждение ограничений из реального запуска. Зрелость адаптера не отменяет
этот результат. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в OpenCode

После копирования общих навыков и JS-проекции в настроенные каталоги OpenCode
перезапустите инструмент и укажите: `Используй навык
agent-workflow-orchestrator для этой задачи: <задача>`. Провайдером, моделью и
инструментами управляет OpenCode.

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит
результатов реализации и принятое итоговое доказательство.
Задача: <опиши задачу или укажи Markdown-файл>
```

Запуск через команду:

```bash
agent-lifecycle start --adapter opencode --file task.md
```

По умолчанию команда не запускает OpenCode. Подробнее: [использование ALK с
адаптером](usage-modes.md).
