# Адаптер Goose

Адаптер Goose имеет статус `VERIFIED` для Goose `1.45.0` на проверенной
локальной связке провайдера и модели. Он объявляет ACP как нейтральную
возможность хоста и не переносит имена провайдера или модели в ядро ALK.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/goose/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/goose/adapter.descriptor.json \
  --skip-host-commands
```

Подтверждения находятся в `docs/adapters/evidence/goose-live-verified.md` и
матрице поддержки. Проверенный диапазон включает Goose `1.45.0`, локальную
связку провайдера и модели и перечисленные подтверждения.

Управляемые сессии поддерживаются как `WRAPPER_ONLY`: ALK связывает работу с
рабочим циклом и прогрессом, но прямой безопасный запуск CLI хоста остаётся за
обёрткой или оператором.

## Запуск только для планирования

Точная версия профиля: `1.45.0`. Состояние профиля: `CANDIDATE`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Маршрут без
профиля и сессии через стандартный ввод образует статический профиль-кандидат;
порядок его квалификации описан в руководстве по планированию.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter goose --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/goose.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/goose.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/goose.json
```

Маршрут планирования использует статус и подтверждения из раздела [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в Goose

Документированный маршрут Goose — команда в терминале. Через отдельную
проверенную обвязку можно вызвать те же команды ALK:

```bash
agent-lifecycle start --adapter goose --file task.md
```

Команда создаёт входные артефакты ALK. Для работы хоста используйте маршрут
запуска через проверенный профиль. Подробнее: [использование ALK с
адаптером](usage-modes.md).
