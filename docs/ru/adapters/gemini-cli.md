# Адаптер Gemini CLI

Проекция Gemini CLI является `EXPERIMENTAL`. Она содержит локальный
контролируемый запуск, обвязку реального хоста и манифест возможностей, но не
заявляет `VERIFIED`, промышленную готовность или конкретные имена моделей в
переносимых артефактах.

Локальная проверка перед реальным запуском:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/gemini-cli/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/gemini-cli/adapter.descriptor.json \
  --skip-host-commands

python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host gemini-cli \
  --evidence <adapter-conformance-evidence.json>
```

Gemini CLI `0.46.0` прошёл безопасный локальный осмотр команд версии, справки,
режима без интерфейса, потокового JSON, выбора модели, прав доступа, навыков,
расширений, MCP и локального маршрута Gemma. Резюме:
`docs/adapters/evidence/gemini-cli-0.10.0.md`.

Текущая причина блокировки: `BLOCKED_UNSUPPORTED_CLIENT_TIER`. Локальный
уровень Gemini Code Assist не даёт получить подтверждение реального запуска,
поэтому зрелость остаётся `EXPERIMENTAL`.
