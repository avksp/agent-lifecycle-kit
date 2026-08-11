# Adapter event capture matrix

Adapter event capture is a declared offline capability. It means an adapter can
map host activity into neutral `agent-adapter-event.v1` events and bind them
with `agent-adapter-event-stream-receipt.v1`. Event capture remains
adapter-owned, while core validates the portable event and receipt contracts.

Hook setup belongs to the operator or adapter. ALK core validates portable
event receipts and lifecycle state.

| Adapter | Native hook | Wrapper route | Receipt route | Hook ownership | Boundary |
| --- | --- | --- | --- | --- | --- |
| claude | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/claude/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| codex | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/codex/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| cursor | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/cursor/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| gemini-cli | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/gemini-cli/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| goose | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/goose/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| grok-build | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/grok-build/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| hermes | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/hermes/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| kimi-code | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/kimi-code/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| opencode | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/opencode/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| openinterpreter | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/openinterpreter/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| pi | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/pi/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |
| qwen-code | Host-specific hook route | Wrapper records bounded CLI operation events | `conformance/adapters/qwen-code/event-stream-receipt.json` | Operator/adapter-owned | `adapter-owned` |

The matrix is a source-tree documentation route. Live lifecycle proof uses the
host-specific conformance, calibration and final-proof evidence defined by the
adapter support policy.
