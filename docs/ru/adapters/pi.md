# Адаптер Pi

Адаптер Pi имеет статус `VERIFIED` для Pi `0.83.0` на проверенной локальной
связке провайдера и модели. Проекция использует RPC/JSON и AGENTS/agentskills,
но не заявляет ACP, публичное одобрение или промышленную готовность.

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
ALK не хардкодит имена ключей и не записывает значения секретов.

## Запуск только для планирования

Точная версия профиля: `0.83.0`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Список инструментов только для чтения существует, но ограниченная передача результата через стандартный ввод не подтверждена.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter pi --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/pi.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/pi.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/pi.json
```

Успешная проверка версии не разрешает запуск планирования.
`managedLaunch.status` остаётся `WRAPPER_ONLY`, а зрелость адаптера не повышает
состояние поддержки планирования. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).
