# Матрица отображения прогресса

Поддержка прогресса описывается отдельно от зрелости адаптера. Для всех
адаптеров это остаётся режимом чтения и отображения.

| Адаптер | Поддержка прогресса | Подключение к командам ALK | Прямой hook хоста | Примечание |
| --- | --- | --- | --- | --- |
| Codex | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Обёртка может включить `--progress-hook stderr` или подтверждение. |
| Claude Code | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Телеметрия остаётся на стороне хоста; ALK читает только переданные подтверждения. |
| Cursor | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Только ручная команда, пока Cursor остаётся `EXPERIMENTAL`. |
| Gemini CLI | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Только ручная команда, пока не описана обёртка. |
| Goose | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | ACP остаётся за отдельной безопасной пробой; прогресс является локальным отображением. |
| Grok Build | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Обёртка может вызывать отображение прогресса после шагов рабочего цикла ALK. |
| Hermes | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Команда запускается после переходов рабочего цикла ALK. |
| Kimi Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Только ручная команда до работ по повышению зрелости на реальном хосте. |
| OpenCode | `WATCH` | `workflow run/task-result/task-accept/finalize` | Не заявлен | Нормализация телеметрии хоста остаётся вне ядра. |
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
прямым hook хоста и подтверждением. `UNSUPPORTED` означает, что поддерживаемого
hook или обёртки пока нет. Эта матрица не заявляет неподтверждённые прямые
hooks хоста.

Подключение к ALK-командам работает только если оператор или обёртка запускает
поддерживаемые команды рабочего цикла с `--progress-hook stderr` или
`--progress-hook receipt --progress-receipt <path>`. Установка плагина сама по
себе не доказывает полный жизненный цикл.
