# Матрица поддержки адаптеров

Матрица фиксирует заявление исходного дерева о поддержке адаптеров. Она не
заменяет локальные проверки: перед использованием нужно запускать `diagnose`,
`adapter validate` и `adapter inspect`.

| Хост | Зрелость | Что это значит |
| --- | --- | --- |
| Codex | `VERIFIED` | Проверен для Codex CLI 0.145.0. |
| Claude Code | `VERIFIED` | Проверен для Claude Code 2.1.220. |
| OpenCode | `VERIFIED` | Проверен для OpenCode CLI 1.18.9. |
| Hermes | `VERIFIED` | Проверен для Hermes Agent v0.19.0. |
| Qwen Code | `VERIFIED` | Проверен для Qwen Code 0.21.0 на host-local provider/model связке. |
| Cursor | `EXPERIMENTAL` | Локальный осмотр проходит, но подтверждений из реального запуска недостаточно. |
| Gemini CLI | `EXPERIMENTAL` | Проверка реальным вызовом ограничена текущим уровнем Gemini Code Assist. |
| Goose | `VERIFIED` | Проверен для Goose 1.45.0 на host-local provider/model связке; public directory approval не заявлен. |
| Kimi Code | `EXPERIMENTAL` | Нужен настроенный провайдер и алиас модели. |
| Grok Build | `VERIFIED` | Проверен для Grok Build 0.2.117 на host-local provider/model связке; public directory approval не заявлен. |
| OpenInterpreter | `VERIFIED` | Проверен для `interpreter` 0.0.34 на host-local provider/model связке; live conformance, calibration, containment и lifecycle proof прошли локально, public directory approval не заявлен. |
| Pi | `VERIFIED` | Проверен для Pi 0.83.0 на host-local provider/model связке; live conformance, calibration, containment, host-env hygiene и lifecycle proof прошли локально, public directory approval не заявлен. |

`VERIFIED` относится только к указанному диапазону хоста и не означает
публичное одобрение каталога, npm-публикацию или готовность других версий.

Capability bench evidence — это drift detector для live conformance. План
строится из `agent-adapter-capability-manifest.v1`, не запускает live calls,
не меняет maturity и не заявляет production promotion. Проверка evidence
сравнивает live host receipts с планом и падает при пропущенной planned
operation, synthetic replay для live-required operation или обходе host-protocol
envelope.

Sandbox evidence использует только `agent-sandbox-receipt.v1`. Partial
process-tree containment и credential proxy границы записываются в details
receipt; значения секретов и полные пути к приватным env-file недопустимы.
