# Adapter event capture

Adapter event capture records host activity as neutral ALK evidence. Adapter
metadata declares the capability with `adapter-event-stream` and
`agent-adapter-event.v1`; the support level is recorded in the adapter support
matrix. The producer boundary is `adapter-owned`.

Hook ownership: the operator or adapter configures the host route. ALK core
validates portable event receipts and lifecycle state; the portable receipt
stays neutral.

An event stream must validate with `agent-adapter-event-stream-validation.v1`.
Completed streams include session start, task launch, command completion,
write summary and task completion. Blocked streams end with `task.blocked`
instead of pretending the task completed.

`agent-adapter-event-stream-receipt.v1` binds the validated stream to the
adapter descriptor digest, event stream digest, lineage, event count and
producer boundary. `agent-adapter-event-capture-validation.v1` fails closed
when declared event capture has no stream, no receipt, malformed events or
stale digests.

```bash
agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
agent-lifecycle adapter event-capture-check --descriptor <adapter.descriptor.json> --capability-manifest <capabilities.manifest.json> --receipt <event-stream-receipt.json> --event <adapter-event-1.json>
```

Event categories stay generic: command, file-change, lifecycle-transition,
model-usage, user-decision and validation. Core does not depend on native host
callback names.

The adapter-level matrix is in
[Adapter event capture matrix](../adapters/event-capture-matrix.md). It lists
native-hook status, wrapper route, receipt route and hook ownership for the
bundled adapters.
