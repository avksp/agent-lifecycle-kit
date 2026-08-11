# Codex event bridge

This bridge describes how a Codex wrapper can turn bounded host activity into
portable ALK events. Hook ownership belongs to the operator or adapter, while
ALK core validates the portable event and receipt contracts. The producer
boundary is `adapter-owned`; the setup action is `operator-owned`.

## Receipt route

- Event schema: `agent-adapter-event.v1`.
- Receipt schema: `agent-adapter-event-stream-receipt.v1`.
- Fixture stream: `conformance/adapters/codex/event-stream.json`.
- Fixture receipt: `conformance/adapters/codex/event-stream-receipt.json`.
- Validation command:

```bash
python3 tools/release/validate_adapter_event_guidance.py \
  --evidence work/event-guidance.json
```

The fixture is offline conformance evidence. It does not claim public directory
approval, production promotion or broader Codex host support.
