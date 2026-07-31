# Episode retrieval

Episode retrieval — лёгкий механизм контекста поверх явно переданных receipt
или session-summary артефактов. Он rebuildable, bounded и не является source of
truth.

## Контракты

- `agent-episode-index.v1`: компактный episode index по явным artifact paths.
- `agent-episode-index-validation.v1`: структурная проверка index.
- `agent-episode-retrieval.v1`: ограниченный результат поиска по query.

Index использует существующий evidence index и сохраняет digest provenance для
каждого episode. Results содержат `sourcePath`, `artifactDigest`, компактное
summary и chain state.

## Chain awareness

Если передан `agent-receipt-hash-chain.v1`, episode получает `chainVerified`
только когда artifact path и digest совпадают с entry в цепочке. Если matching
chain нет, retrieval всё равно работает, но возвращает `chainUnchecked: true`.

Это важно: retrieval помогает подобрать контекст, но unchecked retrieval не
является доказательством.

## Python API

```python
from pathlib import Path

from agent_lifecycle.context import build_episode_context

context = build_episode_context(
    Path("."),
    ["final/final-proof.json", "reviews/task-review.json"],
    query="regression proof",
    max_results=4,
)
```

## Границы

- Episode retrieval optional и запускается только явно.
- Он не читает произвольные пути; caller передаёт repo-relative artifacts.
- Он не возвращает raw artifact bodies.
- Он fail closed, если результат превышает target context budget.
