# Матрица захвата событий адаптеров

Захват событий адаптера — это объявленная офлайн-возможность. Она означает, что
адаптер может перевести активность хоста в нейтральные события
`agent-adapter-event.v1` и связать их с
`agent-adapter-event-stream-receipt.v1`. Настройка hook принадлежит оператору
или адаптеру, а ядро проверяет переносимые события и состояние жизненного цикла.

Владелец настройки: оператор или адаптер. Оператор или адаптер задаёт
конфигурацию hook и подписку на события хоста, а ядро ALK проверяет
переносимый поток и его связь с жизненным циклом.

| Адаптер | Hook хоста | Маршрут через обёртку | Маршрут артефакта | Владелец настройки | Граница |
| --- | --- | --- | --- | --- | --- |
| claude | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/claude/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| codex | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/codex/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| cursor | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/cursor/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| gemini-cli | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/gemini-cli/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| goose | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/goose/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| grok-build | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/grok-build/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| hermes | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/hermes/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| kimi-code | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/kimi-code/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| opencode | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/opencode/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| openinterpreter | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/openinterpreter/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| pi | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/pi/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |
| qwen-code | Маршрут hook хоста | Обёртка записывает события ограниченной CLI-операции | `conformance/adapters/qwen-code/event-stream-receipt.json` | Оператор или адаптер | `adapter-owned` |

Матрица описывает маршрут в исходном дереве. Для установления уровня поддержки
нужны проверка реального хоста, калибровка расхода и финальное подтверждение
жизненного цикла.
