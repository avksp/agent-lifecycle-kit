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
