# Проверка завершения

`completionCheck` — необязательное поле спецификации для задач, где нужен
наблюдаемый признак завершения сверх приёмки задачи и финального аудита.

При принятии плана workflow переносит это поле в состояние запуска.
`workflow finalize` затем отказывает, пока не появится
`agent-completion-check-receipt.v1` со статусом `PASS`, той же привязкой к
запуску, пакету, ревизии плана, отпечатку плана, исходной ревизии и всем
обязательным подтверждениям.

Минимальный фрагмент спецификации:

```json
{
  "completionCheck": {
    "schemaVersion": "agent-completion-check.v1",
    "checkId": "final-user-outcome",
    "kind": "verification",
    "description": "The requested outcome is demonstrated by the final evidence.",
    "receiptPath": "final/completion-check-receipt.json",
    "requiredEvidenceIds": ["EV-FINAL"]
  }
}
```

Для решений оператора используйте `kind: "external-action"`. Тогда подтверждение
должно ссылаться на `agent-external-action-receipt.v1` из обычного перехода
workflow, а не создавать отдельный путь согласования.

## Финальная развилка

`agent-completion-gate-receipt.v1` — детерминированное решение по текущим
подтверждениям: `STOP`, `CONTINUE`, `ESCALATE`, `SPLIT` или `FOLLOW_UP`.

```bash
agent-lifecycle specification completion-gate \
  --state <run.state.json> \
  --final-audit <final-audit.json> \
  --input <completion-gate-input.json> \
  --out <completion-gate.json>
```

`STOP` и `FOLLOW_UP` допустимы только при принятых обязательных задачах,
успешных проверках, отсутствии блокировок workflow, отсутствии финальных
блокеров в отложенной работе и готовом финальном аудите.

`workflow finalize` может принять результат через
`--completion-gate-receipt <completion-gate.json>`. Если отпечатки входов не
совпадают с текущим состоянием и финальным аудитом, финализация отказывает.
