# Адаптер Pi

Адаптер Pi имеет уровень поддержки `VERIFIED` для Pi `0.83.0` на проверенной
локальной связке провайдера и модели. Проекция использует RPC/JSON и
AGENTS/agentskills.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/pi/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/pi/adapter.descriptor.json \
  --skip-host-commands
```

Принятое резюме: `docs/adapters/evidence/pi-live-verified.md`. Проверка
включала проверку реального хоста, калибровку, ограничения среды, проверку
env-файла и финальное подтверждение жизненного цикла.

Провайдер, модель и ключи задаются в конфигурации Pi или локальном env-файле.
ALK получает имена разрешённых переменных от обвязки, а значения секретов
остаются в механизме учётных данных хоста.

## Запуск только для планирования

Точная версия профиля: `0.83.0`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Список
инструментов только для чтения доступен; порядок квалификации добавляет
ограниченную передачу результата через стандартный ввод.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter pi --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/pi.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/pi.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/pi.json
```

Маршрут планирования использует статус и подтверждения из раздела [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера Pi каждая операция дескриптора (`install`, `discover`, `validate-envelope`, `launch`, `model-route-execution`, `wait`, `cancel`, `resume`, `tool-execution`, `adapter-event-stream`, `result-collection`, `usage-attestation`, `task-audit`, `final-audit`) публикует
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

## Использование ALK в Pi

Подключите навык `agent-workflow-orchestrator` из отмеченной версии через
штатную настройку AGENTS/Agent Skills в Pi и запросите его для задачи.
Настройка навыков остаётся операторской конфигурацией хоста.

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит
результатов реализации и принятое итоговое доказательство.
Задача: <опиши задачу или укажи Markdown-файл>
```

Этот запрос применим только после настройки навыков во внешнем инструменте.

Явный запуск через команду:

```bash
agent-lifecycle start --adapter pi --file task.md
```

Команда создаёт входные артефакты ALK. Для работы хоста используйте маршрут
запуска через проверенный профиль. Подробнее: [использование ALK с адаптером](usage-modes.md).
