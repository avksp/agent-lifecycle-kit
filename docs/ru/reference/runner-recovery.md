# Runner Recovery Receipts

Runner recovery receipts — дополнительные артефакты для долгих задач и
нескольких попыток. Они не заменяют workflow state; их задача — зафиксировать,
что произошло с попыткой: snapshot, restore, abandon или selected-attempt.

## Attempt Snapshots

`agent-runner-attempt-snapshot-receipt.v1` фиксирует одно действие:

- `snapshot`: digest-bound снимок runner/attempt state.
- `restore`: digest снимка, из которого восстановили попытку.
- `abandon`: причина, по которой попытка больше не выбрана.
- `select`: выбранная попытка и digest выбранного результата.

Валидация пересчитывает digest snapshot и receipt, проверяет lineage и падает,
если restore или selected attempt заявлены без нужного digest.

## Worker Leases

`agent-worker-lease-receipt.v1` фиксирует lease и heartbeat worker-а.
Состояние вычисляется детерминированно:

- `active`, если `observedAt` не позже `expiresAt`;
- `expired`, если `observedAt` позже `expiresAt`;
- `completed`, если указан `completedAt`.

Это recovery metadata, а не второй scheduler.

## Phase Resources

`agent-phase-resource-measurement.v1` фиксирует токены, длительность и resource
counters по фазам через envelope Release 1.8 usage export. Phase measurements
не используют обязательный USD-cost и отклоняют monetary fields вроде
`cost_usd`.

Receipt содержит вложенный `agent-usage-export.v1`, чтобы переиспользовать
существующие totals и redaction checks.
