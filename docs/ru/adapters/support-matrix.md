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
| Qwen Code | `VERIFIED` | Проверен для Qwen Code 0.21.0 на связке GLM 5.2. |
| Cursor | `EXPERIMENTAL` | Локальный осмотр проходит, но подтверждений из реального запуска недостаточно. |
| Gemini CLI | `EXPERIMENTAL` | Проверка реальным вызовом ограничена текущим уровнем Gemini Code Assist. |
| Goose | `EXPERIMENTAL` | ACP host-capability projection с offline conformance; live promotion не заявлен. |
| Kimi Code | `EXPERIMENTAL` | Нужен настроенный провайдер и алиас модели. |
| Grok Build | `EXPERIMENTAL` | ACP-путь закрыт локальным probe gate; негативный probe фиксируется fail-closed. |
| OpenInterpreter | `EXPERIMENTAL` | Host-local compatible CLI projection с offline conformance. |
| Pi | `EXPERIMENTAL` | RPC/JSON и AGENTS/agentskills projection без live promotion. |

`VERIFIED` относится только к указанному диапазону хоста и не означает
публичное одобрение каталога, npm-публикацию или готовность других версий.
