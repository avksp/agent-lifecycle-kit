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
