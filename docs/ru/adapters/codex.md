# Адаптер Codex

Проекция Codex содержит общие навыки жизненного цикла и манифест плагина Codex.
Корень репозитория является каноническим корнем плагина Codex, а
`adapters/codex/` хранит только сведения проекции хоста.

Текущий уровень поддержки: `VERIFIED` для Codex CLI `0.145.0`. Подтверждение
относится к указанному диапазону версий и описано в локальных артефактах
адаптера.

Установка из отмеченного тега:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref vX.Y.Z
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

Проверка проекции:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/codex/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/codex/adapter.descriptor.json \
  --skip-host-commands
```

Подтверждение описано в `docs/adapters/evidence/codex-cli-0.6.0.md`. Ключи
провайдера остаются в настройках хоста, а `managedLaunch.status` для встроенного
профиля имеет значение `WRAPPER_ONLY`.

## Запуск через проверенный локальный профиль

Для Codex CLI `0.147.0` предусмотрен отдельный локальный профиль с точной
привязкой к версии. Создайте и проверьте его перед зафиксированным вызовом
`start --launch`. Для этого профиля учёт расхода имеет статус `FIXTURE_ONLY`,
а основной проверенный диапазон адаптера остаётся `0.145.0`. См. [запуск
зафиксированной задачи через проверенный профиль](../reference/qualified-host-launch.md).

Для той же точной версии есть кандидат запуска только для планирования, но его
текущее состояние — `PLANNING_ONLY_UNSUPPORTED`: подтверждение ограничений из
реального запуска отсутствует. Поэтому `start --mode plan --launch`
завершается безопасным отказом. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера Codex каждая операция дескриптора (`install`, `discover`, `validate-envelope`, `launch`, `model-route-execution`, `wait`, `cancel`, `resume`, `tool-execution`, `adapter-event-stream`, `result-collection`, `usage-attestation`, `task-audit`, `final-audit`) публикует
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

## Использование ALK в Codex

После установки модуля перезапустите Codex, откройте целевой проект и укажите:
`Используй навык agent-workflow-orchestrator для этой задачи: <задача>`.
Codex управляет моделью и инструментами, а навык требует вызывать ALK и
сохранять артефакты жизненного цикла.

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит
результатов реализации и принятое итоговое доказательство.
Задача: <опиши задачу или укажи Markdown-файл>
```

Для воспроизводимого запуска вне сессии Codex:

```bash
agent-lifecycle start --adapter codex --file task.md
```

Команда создаёт входные артефакты ALK. Для запуска Codex добавьте проверенный
профиль и `--launch`; подтверждение жизненного цикла
формируется переходами состояния и принятыми квитанциями.
Подробнее: [использование ALK с адаптером](usage-modes.md).
