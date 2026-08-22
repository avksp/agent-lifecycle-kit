# Адаптер OpenInterpreter

OpenInterpreter представлен как дополнительный адаптер со статусом `VERIFIED`
для `interpreter` `0.0.34` на проверенной локальной связке провайдера и модели.
Ядро ALK владеет переносимыми артефактами жизненного цикла, а адаптер описывает
только запуск, нормализацию JSONL и ограничения среды.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/openinterpreter/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/openinterpreter/adapter.descriptor.json \
  --skip-host-commands
```

OpenInterpreter может выполнять код, поэтому уровень поддержки включает
подтверждения ограничений среды, калибровку расхода и финальное подтверждение.
Принятое резюме:
`docs/adapters/evidence/openinterpreter-live-verified.md`.

Ключи провайдера остаются локальными для хоста. ALK может передать разрешённые
имена переменных конкретной обвязке, а значения секретов остаются в механизме
учётных данных хоста и не попадают в подтверждения.

## Запуск только для планирования

Точная версия профиля: `0.0.34`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Порядок
квалификации использует надёжный встроенный профиль только для чтения.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter openinterpreter --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/openinterpreter.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/openinterpreter.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/openinterpreter.json
```

Маршрут планирования использует статус и подтверждения из раздела [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера OpenInterpreter каждая операция дескриптора (`install`, `discover`, `validate-envelope`, `launch`, `model-route-execution`, `wait`, `cancel`, `resume`, `tool-execution`, `adapter-event-stream`, `result-collection`, `usage-attestation`, `task-audit`, `final-audit`) публикует
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

## Использование ALK в OpenInterpreter

Документированный маршрут OpenInterpreter — команда в терминале. Через
отдельную проверенную обвязку можно вызвать те же команды ALK:

```bash
agent-lifecycle start --adapter openinterpreter --file task.md
```

Команда создаёт входные артефакты ALK. Для работы хоста используйте маршрут
запуска через проверенный профиль. Подробнее: [использование ALK с
адаптером](usage-modes.md).
