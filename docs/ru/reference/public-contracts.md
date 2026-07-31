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
- `agent-sandbox-receipt.v1`: runtime evidence для filesystem, network,
  process, environment и enforcement source.
- `agent-sandbox-requirement.v1`: fail-closed политика обязательного sandbox
  evidence для high-risk задач.
- `agent-sandbox-capability.v1`: декларация sandbox capabilities адаптера.
- `agent-import-dialect-profile.v1`: профиль внешнего dialect import.
- `agent-episode-index.v1`: rebuildable индекс receipt/session episodes.
- `agent-episode-retrieval.v1`: bounded retrieval result с digest provenance.
- `agent-lifecycle-policy-proposal.v1`: предложение по настройке правил.

## Правило совместимости

Новые схемы должны добавляться явно и проходить `agent-lifecycle contract
check`. Изменение контракта без тестов и документации считается небезопасным.

`agent-fix-impact-receipt.v1` — основной контракт для фиксации влияния
исправления. Он связывает changed files, finding ids, digest root cause,
изменённые и сохранённые behavior contracts, regression evidence и проверку
побочного влияния.

`agent-sandbox-receipt.v1` не заменяет
`agent-worktree-attempt-receipt.v1`. Worktree receipt ограничивает пути записи
в репозитории, а sandbox receipt описывает runtime containment. `UNKNOWN` —
валидное явное состояние capability, но required high-risk policy принимает
только настроенные passing statuses, по умолчанию `PASS`.

`agent-import-dialect-profile.v1` требует `sourceTrusted: false`,
`requiresReview: true` и `freezeBlocked: true`. `nativeDialectProfileDigest`
фиксирует provenance импортированного dialect, но не означает approval.

`agent-episode-retrieval.v1` возвращает bounded context projection по явно
переданным receipt/session artifacts. Result получает `chainVerified` только
при совпадении path и digest с hash-chain entry; иначе state остаётся
`chainUnchecked`.
