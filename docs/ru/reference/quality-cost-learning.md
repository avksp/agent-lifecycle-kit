# Quality-cost learning

Quality-cost learning — локальный advisory loop поверх явных ALK receipts. Он
помогает выбирать самый быстрый достаточный lifecycle path для похожих будущих
задач, сохраняя quality floor.

Он не вызывает provider APIs, не отправляет telemetry, не обучает модель, не
требует USD cost fields и не строит provider/model leaderboards в core.

## Поток

```bash
agent-lifecycle metrics outcome-index \
  --artifact <task-result.json> \
  --artifact <completion-gate.json> \
  --out <outcome-index.json>

agent-lifecycle metrics quality-signals \
  --index <outcome-index.json> \
  --out <quality-cost-signals.json>

agent-lifecycle metrics learn-recommend \
  --signals <quality-cost-signals.json> \
  --task-shape small-fix \
  --current-mode strict \
  --out <recommendation.json> \
  --summary-out <recommendation-summary.json>
```

`agent-task-outcome-index.v1` группирует локальные receipts по task shape,
lifecycle mode, route class и profile. `agent-quality-cost-signals.v1`
показывает success rate, blocker rate, retries, remediation loops, tokens, wall
time и tool calls. `agent-lifecycle-recommendation.v1` остаётся advisory с
`autoApply: false`, confidence, evidence digests, rollback metadata и
`qualityFloorPreserved: true`.

Низкая confidence оставляет current или floor mode. Любое изменение policy
должно идти через явный proposal/apply path.
