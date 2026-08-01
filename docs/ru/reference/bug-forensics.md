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
- `agent-failure-classification-receipt.v1`: нейтральный failure class,
  confidence, matched evidence и digest provenance.
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

Failure classification и flake signals можно привязать к gate receipt. Если
security или race classification совмещены с S2/security risk задачи, gate
требует cross-check evidence вместо тихого принятия слабой проверки.

## Recipes

Bug Forensics recipes — optional metadata для типовых этапов defect repair:

- `issue-classification`: определить класс дефекта и необходимость профиля.
- `reproduction`: доказать red-состояние до правки и привязать artifacts
  digest.
- `investigation`: вести accepted/rejected hypotheses и minimal-patch scope.
- `validation`: доказать same-fingerprint red-to-green и fix impact.
- `review`: проверить gate receipt и optional cross-check evidence.

Recipes не вводят новые receipt schemas. Они ссылаются на существующие Bug
Forensics, proof-integrity и cross-check receipts, выключены по умолчанию и
используют tokens/resources вместо обязательного USD-cost.

## Deferred Analysis

Suspect graph остаётся optional. Flake signals и failure classification уже
могут фиксироваться, но не заменяют reproduction, fingerprint, hypothesis
ledger, regression proof или fix-impact evidence.
