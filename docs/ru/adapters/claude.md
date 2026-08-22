# Адаптер Claude Code

Проекция Claude Code подключает общие навыки жизненного цикла, корневой
`.claude-plugin/plugin.json` и `.claude-plugin/marketplace.json`.

Текущий уровень поддержки: `VERIFIED` для Claude Code `2.1.220` в проверенном
диапазоне хоста. Подтверждение относится к указанной версии и опирается на
локальные артефакты соответствия и жизненного цикла.

Установка из исходного marketplace:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

После установки в интерактивной сессии выполните `/reload-plugins`.

Проверка проекции:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/claude/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/claude/adapter.descriptor.json \
  --skip-host-commands
```

Подтверждение `VERIFIED` описано в
`docs/adapters/evidence/claude-code-0.5.0.md` и матрице поддержки. Для
встроенного профиля `managedLaunch.status` имеет значение `WRAPPER_ONLY`, а
ключи провайдера остаются в настройках хоста.

## Запуск через проверенный локальный профиль

Для Claude Code `2.1.226` предусмотрен отдельный локальный профиль с точной
привязкой к версии. Профиль использует утверждённые аргументы процесса,
сохраняет основной проверенный диапазон `2.1.220`, а учёт токенов имеет статус
`FIXTURE_ONLY`. См. [запуск зафиксированной задачи через проверенный
профиль](../reference/qualified-host-launch.md).

Раздел запуска только для планирования остаётся профилем-кандидатом со
статусом `PLANNING_ONLY_UNSUPPORTED`; его последовательность квалификации
описана в разделе [запуска адаптера только для планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера Claude Code каждая операция дескриптора (`install`, `discover`, `validate-envelope`, `launch`, `model-route-execution`, `wait`, `cancel`, `resume`, `tool-execution`, `adapter-event-stream`, `result-collection`, `usage-attestation`, `task-audit`, `final-audit`) публикует
`declaredLevel: GUIDANCE_ONLY`, `supportedLevel: GUIDANCE_ONLY`,
`qualifiedLevel: GUIDANCE_ONLY` и `qualificationStatus: NO_RECOMMENDATION`.
Статус управляемого запуска - `WRAPPER_ONLY`. Это значения контроля жизненного
цикла для отдельных операций, а не общий уровень поддержки адаптера в матрице.

Страница и навык адаптера объясняют порядок работы ALK внутри хоста. Они не
заявляют, что промпт, плагин или обёртка блокируют действие. Позже для отдельных
операций можно квалифицировать производителя хоста для точной версии, но
одних офлайн-фикстур для повышения уровня недостаточно. См. [необязательный
контроль жизненного цикла](lifecycle-control.md) и [использование ALK с
адаптером](usage-modes.md).

## Использование ALK в Claude Code

После установки модуля выполните `/reload-plugins`, откройте целевой проект и
укажите: `Используй навык agent-workflow-orchestrator для этой задачи:
<задача>`. Claude Code управляет моделью и инструментами, а доказательство
жизненного цикла формируют принятые подтверждения ALK.

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит
результатов реализации и принятое итоговое доказательство.
Задача: <опиши задачу или укажи Markdown-файл>
```

Для воспроизводимого запуска вне сессии Claude Code:

```bash
agent-lifecycle start --adapter claude --file task.md
```

Команда создаёт входные артефакты ALK. Для запуска Claude Code добавьте
проверенный профиль и `--launch`. Подробнее: [использование ALK с
адаптером](usage-modes.md).
