# Адаптер OpenCode

Проекция OpenCode содержит общие навыки жизненного цикла, корневой
`opencode.json`, JS-проекцию под `adapters/opencode/` и манифест возможностей.
Код OpenCode не должен повторно реализовывать планирование, фиксацию плана,
рабочий цикл, проверку или финальный аудит.

Текущий статус: `VERIFIED` для OpenCode CLI `1.18.9`. Это не публикация в npm,
не одобрение публичного каталога и не поддержка непроверенных версий.

Локальная установка зависит от конфигурации OpenCode: скопируйте `skills/*` в
`.opencode/skills/` или `~/.config/opencode/skills/`, а
`adapters/opencode/plugins/agent-lifecycle-kit.js` — в соответствующий каталог
`.opencode/plugins/`.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/opencode/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/opencode/adapter.descriptor.json \
  --skip-host-commands
```

Резюме осмотра: `docs/adapters/evidence/opencode-0.7.0.md`.
Резюме реального запуска: `docs/adapters/evidence/opencode-host-local-live-2026-07-29.md`.
Провайдер, модель, прямой запуск и телеметрия остаются на стороне хоста.
