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
и матрице поддержки. Проверенный диапазон включает Grok Build `0.2.117`,
локальную связку провайдера и модели и ACP-пробу.

Управляемые сессии имеют профиль `WRAPPER_ONLY`; провайдер, модель, прямой
запуск хоста и телеметрия остаются локальной ответственностью хоста.

## Запуск только для планирования

Точная версия профиля: `0.2.118`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Порядок
квалификации использует ограниченную передачу результата через стандартный ввод
и подтверждение ограничений среды.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter grok-build --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/grok-build.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/grok-build.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/grok-build.json
```

Маршрут планирования использует статус и подтверждения из раздела [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в Grok Build

Документированный маршрут Grok Build — команда в терминале. Через отдельную
проверенную обвязку можно вызвать те же команды ALK:

```bash
agent-lifecycle start --adapter grok-build --file task.md
```

Команда создаёт входные артефакты ALK. Для работы хоста используйте
квалифицированный маршрут запуска. Подробнее: [использование ALK с
адаптером](usage-modes.md).
