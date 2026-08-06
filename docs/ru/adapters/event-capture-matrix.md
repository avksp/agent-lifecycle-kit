# Матрица захвата событий адаптеров

Захват событий адаптера — это объявленная офлайн-возможность. Она означает, что
адаптер может перевести активность хоста в нейтральные события
`agent-adapter-event.v1` и связать их с
`agent-adapter-event-stream-receipt.v1`. Это не устанавливает hook, не
разбирает сырую телеметрию хоста в ядре и не меняет зрелость адаптера.

Автоматическая установка: нет. Ядро ALK не меняет настройки хоста и не
подписывается на внутренние события хоста. Если конкретный хост поддерживает
hook, его настройка остаётся ответственностью оператора или адаптера.

| Адаптер | Hook хоста | Маршрут через обёртку | Маршрут артефакта | Автоматическая установка | Граница |
| --- | --- | --- | --- | --- | --- |
| claude | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/claude/event-stream-receipt.json` | Нет | `adapter-owned` |
| codex | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/codex/event-stream-receipt.json` | Нет | `adapter-owned` |
| cursor | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/cursor/event-stream-receipt.json` | Нет | `adapter-owned` |
| gemini-cli | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/gemini-cli/event-stream-receipt.json` | Нет | `adapter-owned` |
| goose | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/goose/event-stream-receipt.json` | Нет | `adapter-owned` |
| grok-build | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/grok-build/event-stream-receipt.json` | Нет | `adapter-owned` |
| hermes | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/hermes/event-stream-receipt.json` | Нет | `adapter-owned` |
| kimi-code | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/kimi-code/event-stream-receipt.json` | Нет | `adapter-owned` |
| opencode | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/opencode/event-stream-receipt.json` | Нет | `adapter-owned` |
| openinterpreter | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/openinterpreter/event-stream-receipt.json` | Нет | `adapter-owned` |
| pi | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/pi/event-stream-receipt.json` | Нет | `adapter-owned` |
| qwen-code | ALK не устанавливает hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/qwen-code/event-stream-receipt.json` | Нет | `adapter-owned` |

Матрица описывает маршрут в исходном дереве, но не является подтверждением
реального запуска. Для повышения зрелости по-прежнему нужны проверка реального
хоста, калибровка расхода и финальное подтверждение жизненного цикла.
