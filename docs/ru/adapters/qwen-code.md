# Адаптер Qwen Code

Проекция Qwen Code имеет статус `VERIFIED` для Qwen Code `0.21.0` на
проверенной локальной связке провайдера и модели. Это совместимость исходного
дерева для конкретного хоста, а не одобрение публичного пакета, каталога или
промышленная готовность.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/qwen-code/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/qwen-code/adapter.descriptor.json \
  --skip-host-commands
```

Принятое подтверждение реального запуска от 2026-07-29 включает:

- Qwen Code `0.21.0`;
- локальную обезличенную связку провайдера и модели;
- 13/13 операций базовой проверки хоста;
- 14/14 запусков калибровки;
- 0 регрессий качества;
- финальное подтверждение жизненного цикла.

Резюме: `docs/adapters/evidence/qwen-code-host-local-live-2026-07-29.md`.
Историческая заметка о каркасе и дымовой проверке:
`docs/adapters/evidence/qwen-code-0.11.0.md`.
Прямой безопасный запуск CLI хоста из ядра не заявляется:
`managedLaunch.status` остаётся `WRAPPER_ONLY`.
