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
- `agent-proof-finding.v1`: стабильная идентичность finding.
- `agent-root-cause-evidence.v1`: подтверждение root cause.
- `agent-fix-impact-receipt.v1`: канонический receipt влияния исправления.
- `agent-receipt-hash-chain.v1`: append-only цепочка receipts.
- `agent-proof-integrity-receipt.v1`: общий receipt целостности
  подтверждений.
- `agent-lifecycle-policy-proposal.v1`: предложение по настройке правил.

## Правило совместимости

Новые схемы должны добавляться явно и проходить `agent-lifecycle contract
check`. Изменение контракта без тестов и документации считается небезопасным.

`agent-fix-impact-receipt.v1` — основной контракт для фиксации влияния
исправления. Он связывает changed files, finding ids, digest root cause,
изменённые и сохранённые behavior contracts, regression evidence и проверку
побочного влияния.
