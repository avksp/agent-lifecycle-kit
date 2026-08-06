# Адаптер Hermes

Проекция Hermes содержит общие навыки жизненного цикла, `skills.sh.json`,
метаданные реестра и команд со слешем под `adapters/hermes/`, а также манифест
возможностей.

Текущий статус: `VERIFIED` для Hermes Agent `v0.19.0`. Это подтверждение
проверенного диапазона хоста, а не одобрение публичного каталога и не
промышленная готовность для всех окружений.

Установка отдельного навыка из отмеченного тега:

```bash
hermes skills install https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/vX.Y.Z/skills/agent-workflow-orchestrator/SKILL.md
```

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/hermes/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/hermes/adapter.descriptor.json \
  --skip-host-commands
```

Резюме локального осмотра: `docs/adapters/evidence/hermes-0.8.0.md`.
Принятое резюме реального запуска: `docs/adapters/evidence/hermes-host-local-live-2026-07-29.md`.
Прямой безопасный запуск CLI хоста из ядра не заявляется.
