# Адаптер Gemini CLI

Проекция Gemini CLI имеет уровень поддержки `EXPERIMENTAL`. Она содержит
манифест возможностей, контролируемый запуск и маршрут подтверждения реального
хоста. Выбор провайдера и модели остаётся в настройках Gemini CLI.

Локальная проверка перед реальным запуском:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/gemini-cli/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/gemini-cli/adapter.descriptor.json \
  --skip-host-commands

python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host gemini-cli \
  --evidence <adapter-conformance-evidence.json>
```

Gemini CLI `0.46.0` прошёл безопасный локальный осмотр команд версии, справки,
режима без интерфейса, потокового JSON, выбора модели, прав доступа, навыков,
расширений, MCP и локального маршрута Gemma. Резюме:
`docs/adapters/evidence/gemini-cli-0.10.0.md`.

Текущая причина в матрице поддержки: `BLOCKED_UNSUPPORTED_CLIENT_TIER`.
Следующий этап — получить подтверждения реального хоста, калибровки и
жизненного цикла на поддерживаемом уровне Gemini Code Assist.

Локальный нормализатор `stream-json` имеет состояние `FIXTURE_ONLY`.
Исполнитель и испытательный стенд используют один ограниченный разбор, но его
результат имеет статус `ESTIMATED` до отдельного подтверждения диапазона версий
Gemini CLI. Подробнее:
[локальный учёт токенов хоста](../reference/host-local-token-accounting.md).

## Запуск только для планирования

Точная версия профиля: `0.46.0`. Состояние профиля: `CANDIDATE`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Режим согласования плана и передача через стандартный ввод образуют статический профиль-кандидат, но принятого подтверждения реального запуска пока нет.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter gemini-cli --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/gemini-cli.json
```

Допустимость запуска планирования определяется статусом профиля и матрицей
поддержки. `managedLaunch.status` имеет значение `WRAPPER_ONLY`; порядок
квалификации описан в разделе [запуска адаптера только для
планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера Gemini CLI каждая операция дескриптора (`cancel`, `discover`, `final-audit`, `install`, `launch`, `model-route-execution`, `result-collection`, `resume`, `task-audit`, `tool-execution`, `adapter-event-stream`, `usage-attestation`, `validate-envelope`, `wait`) публикует
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

## Использование ALK в Gemini CLI

Подключите общий каталог `skills/` из отмеченной версии через штатные настройки
Gemini CLI и запросите `agent-workflow-orchestrator` либо используйте
поддерживаемую команду:

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит
результатов реализации и принятое итоговое доказательство.
Задача: <опиши задачу или укажи Markdown-файл>
```

После настройки навыков во внешнем инструменте используйте этот запрос внутри
сессии.

```bash
agent-lifecycle start --adapter gemini-cli --file task.md
```

Команда создаёт входные артефакты ALK. Для запуска Gemini CLI добавьте
проверенный профиль и `--launch`. Подробнее: [использование ALK с
адаптером](usage-modes.md).
