# Матрица отображения прогресса

Поддержка прогресса является отдельным измерением уровня поддержки адаптера. Для
всех адаптеров это режим чтения и отображения.

| Адаптер | Поддержка прогресса | Подключение к командам ALK | Маршрут хоста | Примечание |
| --- | --- | --- | --- | --- |
| Codex | `WATCH` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Обёртка может включить `--progress-hook stderr` или подтверждение. |
| Claude Code | `WATCH` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Телеметрия остаётся на стороне хоста; ALK читает только переданные подтверждения. |
| Cursor | `MANUAL` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Используйте команду отображения после переходов рабочего цикла ALK. |
| Gemini CLI | `MANUAL` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Используйте команду отображения после переходов рабочего цикла ALK. |
| Goose | `WATCH` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | ACP остаётся за отдельной безопасной пробой; прогресс является локальным отображением. |
| Grok Build | `WATCH` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Обёртка может вызывать отображение прогресса после шагов рабочего цикла ALK. |
| Hermes | `MANUAL` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Команда запускается после переходов рабочего цикла ALK. |
| Kimi Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Используйте команду отображения после переходов рабочего цикла ALK. |
| OpenCode | `WATCH` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Нормализация телеметрии хоста остаётся вне ядра. |
| OpenInterpreter | `MANUAL` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Ключи провайдера остаются на стороне хоста. |
| Pi | `MANUAL` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Ключи провайдера остаются на стороне хоста. |
| Qwen Code | `MANUAL` | `workflow run/task-result/task-accept/finalize` | На стороне хоста | Ручная команда после переходов жизненного цикла. |

Общая команда:

```bash
agent-lifecycle report progress-bridge \
  --adapter <adapter-id> \
  --support-level <AUTO|WATCH|MANUAL|UNSUPPORTED> \
  --hook-point <hook-point> \
  --state <workflow-state.json> \
  --terminal
```

`AUTO` используется для адаптеров с реализованной ALK-обёрткой или прямым hook
хоста и подтверждением. `UNSUPPORTED` обозначает маршрут hook или обёртки,
который проходит квалификацию. Матрица показывает точный способ работы для
каждого адаптера.

Подключение к ALK-командам работает, когда оператор или обёртка запускает
поддерживаемые команды рабочего цикла с `--progress-hook stderr` или
`--progress-hook receipt --progress-receipt <path>`. Установка плагина сама по
себе является входом в маршрут, а подтверждение жизненного цикла формируется
принятыми квитанциями ALK.
