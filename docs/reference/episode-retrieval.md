# Episode retrieval

Episode retrieval is a lightweight context mechanism over explicit receipt or
session-summary artifacts. It is rebuildable, bounded and not a source of
truth.

## Contracts

- `agent-episode-index.v1`: compact episode index built from explicit artifact
  paths.
- `agent-episode-index-validation.v1`: structural validation for the index.
- `agent-episode-retrieval.v1`: bounded retrieval result for a query.

The index wraps the existing evidence index and preserves digest provenance for
each episode. Results include `sourcePath`, `artifactDigest`, compact summary
fields and chain state.

## Chain awareness

When an `agent-receipt-hash-chain.v1` is supplied, an episode is marked
`chainVerified` only if the artifact path and digest match a chain entry. When
no matching chain is available, retrieval still works but returns
`chainUnchecked: true`.

This is intentional: retrieval may help context selection, but unchecked
retrieval is not proof.

## External context hints

Episode retrieval can include imported external context receipts:

```bash
agent-lifecycle context episode-retrieve \
  --project-root . \
  --artifact work/run/final-proof.json \
  --external-context work/context/project-memory.external-context.json \
  --query "regression proof"
```

The external context is returned as `externalContextHints` with
`sourceOfTruth: false` and `proof: false`. It can help the operator choose
context, but it cannot satisfy evidence, review or final proof requirements.

## Python API

```python
from pathlib import Path

from agent_lifecycle.context import build_episode_context

context = build_episode_context(
    Path("."),
    ["final/final-proof.json", "reviews/task-review.json"],
    query="regression proof",
    external_context_hints=[],
    max_results=4,
)
```

## Boundaries

- Episode retrieval is optional and disabled unless called explicitly.
- It does not read arbitrary paths; callers pass repository-relative artifacts.
- It does not return raw artifact bodies.
- External context hints are optional and non-proof.
- It fails closed when the result exceeds the target context budget.
