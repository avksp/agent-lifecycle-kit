# Целостность подтверждений

Целостность подтверждений — это дополнительный слой финального proof для
запусков, где нужно показать не только факт прохождения финальной проверки, но
и причинную цепочку исправления. Режим подходит для багфиксов, регрессий,
security-дефектов, release blockers и других рискованных изменений.

Цепочка выглядит так:

```text
finding -> root cause -> fix impact -> regression evidence -> hash chain -> final proof
```

Режим не включается для обычных задач по умолчанию. Запуск включает его через
`proofIntegrityRequired: true`, через `proofIntegrityPolicy.mode` со значением
`required`, `bug-forensics` или `strict`, либо через
`proofIntegrityRequired: true` в финальном аудите.

## Контракты

- `agent-proof-finding.v1`: стабильная идентичность finding. `findingId`
  строится из нормализованных rule/category/severity/path/symbol/message, а не
  из номера строки или временного id ревью.
- `agent-root-cause-evidence.v1`: подтверждение root cause со статусом
  `CONFIRMED`, `REJECTED` или `INCONCLUSIVE`. Для обязательных findings
  финальная проверка требует подтверждённый root cause.
- `agent-fix-impact-receipt.v1`: канонический receipt влияния исправления. Он
  фиксирует изменённые файлы, связанные findings, digest root cause, изменения
  поведения, сохранённые контракты, regression evidence и проверку побочного
  влияния.
- `agent-receipt-hash-chain.v1`: append-only цепочка receipts. Каждая запись
  хэширует artifact identity и предыдущий entry hash.
- `agent-hash-chain-migration-policy.v1`: политика миграции. Новые запуски
  требуют chain; старые запуски без chain требуют явный exemption или backfill.
- `agent-proof-integrity-receipt.v1`: общий receipt, который связывает finding,
  root cause, fix impact, chain и migration evidence.
- `agent-proof-integrity-validation.v1`: результат fail-closed проверки.

## Финализация

`workflow finalize` принимает необязательный proof-integrity receipt:

```bash
agent-lifecycle workflow finalize \
  --state run.state.json \
  --operation-id finalize-op \
  --expected-revision 7 \
  --source-revision <sha> \
  --final-audit final/final-audit.json \
  --proof final/proof.json \
  --proof-integrity final/proof-integrity.json \
  --reason "accepted release evidence"
```

Если proof integrity обязателен, но `--proof-integrity` не передан,
финализация падает с `proof-integrity-receipt-missing`. Если receipt передан,
но lineage, digest, required finding ids, required root-cause digests,
fix-impact digests или hash-chain links не совпадают, финализация падает с
`proof-integrity-validation-failed`.

При успешной проверке final proof получает блок `proofIntegrity` с identity
receipt и validation result, а workflow state сохраняет `proofIntegrityReceipt`.

## Миграция

Стандартная политика — `required-for-new-runs`:

- новые запуски должны иметь `agent-receipt-hash-chain.v1`;
- legacy-запуски могут быть без chain только со структурированным
  `legacyHashChainExemption`;
- если старые артефакты доступны, предпочтителен backfill;
- текстовое описание не заменяет digest-проверяемые receipts.

Так старые запуски остаются читаемыми, а новые подтверждения становятся
append-only и проверяемыми по digest.
