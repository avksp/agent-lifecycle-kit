# Матрица отображения прогресса

Поддержка прогресса описывается отдельно от зрелости адаптера. Для всех
адаптеров bridge остаётся режимом чтения и отображения.

| Адаптер | Поддержка прогресса | Hook ALK-команд | Native hook хоста | Примечание |
| --- | --- | --- | --- | --- |
| Codex | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Обёртка может включить `--progress-hook stderr` или receipt. |
| Claude Code | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Telemetry остаётся на стороне хоста; ALK читает только переданные receipts. |
| Cursor | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Только ручная команда, пока Cursor остаётся `EXPERIMENTAL`. |
| Gemini CLI | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Только ручная команда, пока не описана обёртка. |
| Goose | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | ACP остаётся probe-gated; прогресс является локальным отображением. |
| Grok Build | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Обёртка может вызывать bridge после шагов ALK workflow. |
| Hermes | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Команда запускается после переходов ALK workflow. |
| Kimi Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Только ручная команда до live promotion работ. |
| OpenCode | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Нормализация telemetry хоста остаётся вне core. |
| OpenInterpreter | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Ключи провайдера остаются на стороне хоста. |
| Pi | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Ключи провайдера остаются на стороне хоста. |
| Qwen Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Ручная команда после переходов жизненного цикла. |

Общая команда:

```bash
agent-lifecycle report progress-bridge \
  --adapter <adapter-id> \
  --support-level <AUTO|WATCH|MANUAL|UNSUPPORTED> \
  --hook-point <hook-point> \
  --state <workflow-state.json> \
  --terminal
```

`AUTO` используется только для адаптеров с реализованной ALK-обёрткой или
native hook и подтверждением. `UNSUPPORTED` означает, что поддерживаемого hook
или обёртки пока нет. Эта матрица не заявляет неподдерживаемые native hooks.

Hook ALK-команд работает только если оператор или обёртка запускает
поддерживаемые workflow-команды с `--progress-hook stderr` или
`--progress-hook receipt --progress-receipt <path>`. Установка plugin сама по
себе не доказывает полный жизненный цикл.
