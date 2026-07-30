# Публичные контракты

Публичные контракты — это стабильные схемы JSON, которыми связаны CLI,
документация, тесты и проверочные артефакты.

## Основные контракты

- `agent-completion-check-receipt.v1`: подтверждение завершения.
- `agent-goal-record.v1`: запись цели.
- `agent-objective-snapshot.v1`: компактный снимок цели.
- `agent-runner-state.v1`: состояние управляемого выполнения.
- `agent-follow-up-register.v1`: реестр продолжений.
- `agent-worktree-attempt-receipt.v1`: подтверждение изоляции рабочего дерева.
- `agent-adapter-event-stream-receipt.v1`: поток событий адаптера.
- `agent-review-verdict.v1`: проверочный вердикт.
- `agent-lifecycle-policy-proposal.v1`: предложение по настройке правил.

## Правило совместимости

Новые схемы должны добавляться явно и проходить `agent-lifecycle contract
check`. Изменение контракта без тестов и документации считается небезопасным.
