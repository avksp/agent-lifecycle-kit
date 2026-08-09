# Адаптер Kimi Code

Проекция Kimi Code является `EXPERIMENTAL`. В ней есть ограниченный
контролируемый запуск и обвязка реального хоста, но нет `VERIFIED`,
промышленной готовности или переносимых имён провайдера и модели.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/kimi-code/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/kimi-code/adapter.descriptor.json \
  --skip-host-commands

python tools/live_hosts/kimi_code_harness.py \
  --mode fixture-check \
  --baseline conformance/core/adapter-baseline.v1.json \
  --report <kimi-code-fixture-check.json>
```

Kimi Code `0.30.0` прошёл безопасный локальный осмотр версии, справки,
headless-режима, потокового JSON, выбора модели, режимов прав, каталога skills,
провайдеров, экспорта сессии и ACP stdio discovery. Резюме:
`docs/adapters/evidence/kimi-code-0.12.0.md`.

Текущая причина блокировки: `BLOCKED_HOST_MODEL_NOT_CONFIGURED`. Пока провайдер
и алиас модели не настроены, подтверждение реального запуска, калибровку и
финальное подтверждение получить нельзя.

Локальный нормализатор `stream-json` имеет состояние `FIXTURE_ONLY`.
Исполнитель и испытательный стенд используют один ограниченный разбор, но его
результат не подходит для S1/S2. Подробнее:
[локальный учёт токенов хоста](../reference/host-local-token-accounting.md).
