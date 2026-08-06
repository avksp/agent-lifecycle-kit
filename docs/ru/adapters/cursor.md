# Адаптер Cursor

Проекция Cursor содержит общие навыки жизненного цикла, корневой
`.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json` и манифест
возможностей `adapters/cursor/capabilities.manifest.json`.

Текущий статус: `EXPERIMENTAL`. Локальный безопасный осмотр Cursor Agent
`2026.07.23-e383d2b` прошёл, но для `VERIFIED` не хватает принятых
подтверждений реального запуска, калибровки расхода и финального подтверждения
жизненного цикла.

Локальная проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/cursor/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/cursor/adapter.descriptor.json \
  --skip-host-commands

python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host cursor \
  --evidence <adapter-conformance-evidence.json>
```

Публичная публикация Cursor требует отдельной проверки Cursor Marketplace.
Текущая причина блокировки: локальная Free-подписка не заменяет подтверждение
расхода и финальное подтверждение. Прямой безопасный запуск CLI хоста из ядра не
заявляется.
