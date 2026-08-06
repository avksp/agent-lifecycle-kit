# Адаптер Claude Code

Проекция Claude Code подключает общие навыки жизненного цикла, корневой
`.claude-plugin/plugin.json` и `.claude-plugin/marketplace.json`.

Текущий статус: `VERIFIED` для Claude Code `2.1.220` в проверенном диапазоне
хоста. Это локальное заявление по исходному дереву, а не одобрение официального
каталога и не промышленная готовность для всех окружений.

Установка из исходного marketplace:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

После установки в интерактивной сессии выполните `/reload-plugins`.

Проверка проекции:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/claude/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/claude/adapter.descriptor.json \
  --skip-host-commands
```

Подтверждение `VERIFIED` ограничено записью в
`docs/adapters/evidence/claude-code-0.5.0.md` и матрицей поддержки.
Прямой безопасный запуск CLI хоста из ядра не заявляется:
`managedLaunch.status` остаётся `WRAPPER_ONLY`.
