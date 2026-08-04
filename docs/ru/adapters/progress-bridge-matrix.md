# Матрица отображения прогресса

Поддержка прогресса описывается отдельно от зрелости адаптера. Для всех
адаптеров bridge остаётся режимом чтения и отображения.

| Адаптер | Поддержка прогресса | Hook point | Примечание |
| --- | --- | --- | --- |
| Codex | `WATCH` | `side-terminal-watch` | Наблюдение в отдельном терминале или через обёртку после переходов жизненного цикла. |
| Claude Code | `WATCH` | `side-terminal-watch` | Telemetry остаётся на стороне хоста; ALK читает только переданные receipts. |
| Cursor | `MANUAL` | `manual` | Только ручная команда, пока Cursor остаётся `EXPERIMENTAL`. |
| Gemini CLI | `MANUAL` | `manual` | Только ручная команда, пока не описана обёртка. |
| Goose | `WATCH` | `side-terminal-watch` | ACP остаётся probe-gated; прогресс является локальным отображением. |
| Grok Build | `WATCH` | `side-terminal-watch` | Обёртка может вызывать bridge после шагов Grok-side lifecycle. |
| Hermes | `MANUAL` | `manual` | Команда запускается после переходов ALK workflow. |
| Kimi Code | `MANUAL` | `manual` | Только ручная команда до live promotion работ. |
| OpenCode | `WATCH` | `side-terminal-watch` | Нормализация host telemetry остаётся вне core. |
| OpenInterpreter | `MANUAL` | `manual` | Ручная команда; provider credentials остаются host-local. |
| Pi | `MANUAL` | `manual` | Ручная команда; provider credentials остаются host-local. |
| Qwen Code | `MANUAL` | `manual` | Ручная команда после переходов жизненного цикла. |

Общая команда:

```bash
agent-lifecycle report progress-bridge \
  --adapter <adapter-id> \
  --support-level <AUTO|WATCH|MANUAL|UNSUPPORTED> \
  --hook-point <hook-point> \
  --state <workflow-state.json> \
  --terminal
```

`AUTO` используется только для адаптеров с реализованным нативным hook.
`UNSUPPORTED` означает, что поддерживаемого hook или обёртки пока нет. Эта
матрица не заявляет неподдерживаемые native hooks.
