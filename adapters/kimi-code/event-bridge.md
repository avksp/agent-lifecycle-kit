# kimi-code event bridge

This is an EXPERIMENTAL event bridge placeholder. A real host adapter
must translate host lifecycle callbacks into `agent-adapter-event.v1`
records and validate them with `agent-lifecycle adapter event-check`.

The scaffold does not implement runtime dispatch. Unsupported operations
must fail closed until host-specific live conformance evidence exists.
