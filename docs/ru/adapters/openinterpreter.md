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

OpenInterpreter может выполнять код, поэтому повышение зрелости на основе
реального запуска отказывает без подтверждений ограничений среды, калибровки
расхода и финального подтверждения. Принятое резюме:
`docs/adapters/evidence/openinterpreter-live-verified.md`.

Ключи провайдера остаются локальными для хоста. ALK может передать разрешённые
имена переменных конкретной обвязке, но не записывает значения секретов в
подтверждения.

## Запуск только для планирования

Точная версия профиля: `0.0.34`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Установленная команда не предоставляет надёжный встроенный профиль только для чтения.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter openinterpreter --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/openinterpreter.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/openinterpreter.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/openinterpreter.json
```

Успешная проверка версии не разрешает запуск планирования.
`managedLaunch.status` остаётся `WRAPPER_ONLY`, а зрелость адаптера не повышает
состояние поддержки планирования. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в OpenInterpreter

Встроенная проекция OpenInterpreter не устанавливает модуль или навык ALK
внутрь внешнего инструмента. Используйте команду либо отдельную проверенную
обвязку:

Использование ALK внутри сессии этого инструмента не поставляется, поэтому
готового примера запроса внутри сессии нет.

```bash
agent-lifecycle start --adapter openinterpreter --file task.md
```

По умолчанию команда не запускает OpenInterpreter. Подробнее: [использование
ALK с адаптером](usage-modes.md).
