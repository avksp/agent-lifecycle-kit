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
