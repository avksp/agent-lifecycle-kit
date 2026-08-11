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

## Квалифицированный локальный запуск

Для Claude Code `2.1.226` предусмотрен отдельный локальный профиль с точной
привязкой к версии. Профиль использует утверждённые аргументы процесса,
сохраняет основной проверенный диапазон `2.1.220`, а учёт токенов имеет статус
`FIXTURE_ONLY`. См. [квалифицированный запуск внешнего
инструмента](../reference/qualified-host-launch.md).

Раздел запуска только для планирования остаётся профилем-кандидатом со
статусом `PLANNING_ONLY_UNSUPPORTED`; его последовательность квалификации
описана в разделе [запуска адаптера только для планирования](../reference/planning-only-launch.md).

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
квалифицированный профиль и `--launch`. Подробнее: [использование ALK с
адаптером](usage-modes.md).
