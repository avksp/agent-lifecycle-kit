# Адаптер Codex

Проекция Codex содержит общие навыки жизненного цикла и манифест плагина Codex.
Корень репозитория является каноническим корнем плагина Codex, а
`adapters/codex/` хранит только сведения проекции хоста.

Текущий статус: `VERIFIED` для Codex CLI `0.145.0`. Это подтверждение локального
диапазона хоста, а не одобрение публичного каталога плагинов и не универсальная
поддержка всех версий.

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

Подтверждение описано в `docs/adapters/evidence/codex-cli-0.6.0.md`. ALK не
хранит ключи провайдера и не заявляет прямой безопасный запуск CLI хоста из
ядра: `managedLaunch.status` остаётся `WRAPPER_ONLY`.

## Квалифицированный локальный запуск

Для Codex CLI `0.147.0` предусмотрен отдельный локальный профиль с точной
привязкой к версии. Создайте и проверьте его перед зафиксированным вызовом
`start --launch`. Это не заменяет полное подтверждение адаптера для версии
`0.145.0` и не повышает учёт расхода выше `FIXTURE_ONLY`. См.
[квалифицированный запуск внешнего
инструмента](../reference/qualified-host-launch.md).
