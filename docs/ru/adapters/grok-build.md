# Адаптер Grok Build

Адаптер Grok Build имеет статус `VERIFIED` для Grok Build `0.2.117` на
проверенной локальной связке провайдера и модели. Поддержка ACP остаётся
ограниченной безопасной пробой: положительное заявление требует отдельного
подтверждения.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/grok-build/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/grok-build/adapter.descriptor.json \
  --skip-host-commands
```

Подтверждения находятся в `docs/adapters/evidence/grok-build-live-verified.md`
и матрице поддержки. Заявление не означает одобрение публичного каталога,
промышленную готовность или поддержку других версий.

Управляемые сессии имеют профиль `WRAPPER_ONLY`; провайдер, модель, прямой
запуск хоста и телеметрия остаются локальной ответственностью хоста.

## Запуск только для планирования

Точная версия профиля: `0.2.118`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Внешний инструмент пока не имеет подтверждённой ограниченной передачи результата через стандартный ввод.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter grok-build --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/grok-build.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/grok-build.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/grok-build.json
```

Успешная проверка версии не разрешает запуск планирования.
`managedLaunch.status` остаётся `WRAPPER_ONLY`, а зрелость адаптера не повышает
состояние поддержки планирования. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в Grok Build

Встроенная проекция Grok Build не устанавливает модуль или навык ALK внутрь
внешнего инструмента. Используйте команду либо отдельную проверенную обвязку:

Использование ALK внутри сессии этого инструмента не поставляется, поэтому
готового примера запроса внутри сессии нет.

```bash
agent-lifecycle start --adapter grok-build --file task.md
```

По умолчанию команда не запускает Grok Build. Подробнее: [использование ALK с
адаптером](usage-modes.md).
