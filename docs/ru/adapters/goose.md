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
матрице поддержки. Заявление не означает одобрение публичного каталога,
промышленную готовность или совместимость с непроверенными версиями Goose.

Управляемые сессии поддерживаются как `WRAPPER_ONLY`: ALK связывает работу с
рабочим циклом и прогрессом, но прямой безопасный запуск CLI хоста остаётся за
обёрткой или оператором.
