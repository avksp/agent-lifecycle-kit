# Review Verdicts

Structured review verdicts give ALK a compact remediation route without
replacing the full review artifact. `agent-review-verdict.v1` separates four
dimensions:

- requirement fit;
- implementation quality;
- evidence quality;
- residual risk.

Each dimension has a compact status, reason code and summary. Routing carries a
deterministic next action such as accept, fix implementation, strengthen
evidence, reopen the contract or block on external action.

`agent-review-verdict-validation.v1` fails closed when an accepted review has a
failed dimension, unresolved MEDIUM+ finding, or a routing action that does not
match the overall verdict. `agent-review-routing-summary.v1` is the compact
view for small local models; larger models can inspect the full review,
findings and evidence artifacts.

```bash
agent-lifecycle audit review-check --review <task-review.json>
```

When `reviewVerdict` is present in `agent-task-review.v2`, workflow task
acceptance validates it before accepting the task.
