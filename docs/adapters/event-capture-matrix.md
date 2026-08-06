# Adapter event capture matrix

Adapter event capture is a declared offline capability. It means an adapter can
map host activity into neutral `agent-adapter-event.v1` events and bind them
with `agent-adapter-event-stream-receipt.v1`. It does not install hooks, does
not parse raw host telemetry in core and does not change adapter maturity.

No automatic hook installation: ALK core does not write host configuration or
subscribe to native host callbacks. Hook setup, if a host supports it, is
operator-owned or adapter-owned.

| Adapter | Native hook | Wrapper route | Receipt route | Automatic hook claim | Boundary |
| --- | --- | --- | --- | --- | --- |
| claude | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/claude/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| codex | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/codex/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| cursor | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/cursor/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| gemini-cli | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/gemini-cli/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| goose | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/goose/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| grok-build | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/grok-build/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| hermes | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/hermes/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| kimi-code | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/kimi-code/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| opencode | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/opencode/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| openinterpreter | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/openinterpreter/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| pi | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/pi/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |
| qwen-code | Host-specific hook not installed by ALK | Wrapper records bounded CLI operation events | `conformance/adapters/qwen-code/event-stream-receipt.json` | No automatic hook installation | `adapter-owned` |

The matrix is a source-tree documentation route, not live proof. Live lifecycle
proof still requires the host-specific conformance, calibration and final-proof
evidence defined by the adapter maturity policy.
