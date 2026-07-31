# Bug Forensics Profile

Bug Forensics — дополнительный профиль качества для задач, где явно нужно
найти или исправить баг, регрессию, flaky failure, инцидент или security bug.
Для обычных feature-задач профиль выключен по умолчанию.

Профиль требует доказать цепочку:

```text
symptom -> reproduction -> failure fingerprint -> hypotheses -> root cause -> minimal fix -> regression proof -> no collateral damage
```

## Phase 1 Contracts

- `agent-bug-forensics-profile.v1`: описание optional профиля.
- `agent-bug-reproduction-receipt.v1`: баг воспроизведён до правки, команда
  падает, артефакты привязаны digest.
- `agent-failure-fingerprint.v1`: стабильный fingerprint ошибки с опциональной
  связью на `findingId` и `rootCauseDigest`.
- `agent-bug-hypothesis-ledger.v1`: принятые и отвергнутые гипотезы плюс
  minimal-patch gate.
- `agent-regression-proof-receipt.v1`: тот же fingerprint красный до фикса и
  зелёный после.
- `agent-bug-forensics-gate-receipt.v1`: результат workflow gate.
- `agent-bug-forensics-audit.v1`: audit summary для gate receipt.

Для impact используется существующий `agent-fix-impact-receipt.v1`; отдельная
bug-specific fix-impact schema не вводится.

## Cross-Check

Для рискованных багов можно явно включить Release 1.12 cross-check. Он остаётся
capped в tokens/resources и advisory, пока frozen plan не требует blocking.

## Phase 2

Suspect graph, flake detector и bug-class classifier описаны как следующий
этап и не блокируют v1 profile.
