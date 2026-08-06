# Claude Code event bridge

This bridge describes how a Claude Code wrapper can turn bounded host activity
into portable ALK events. It is documentation and conformance guidance, not
native hook installation.

No automatic hook installation: ALK core does not write Claude Code
configuration or subscribe to Claude-native callbacks. The producer boundary is
`adapter-owned`; the setup action is `operator-owned`.

## Receipt route

- Event schema: `agent-adapter-event.v1`.
- Receipt schema: `agent-adapter-event-stream-receipt.v1`.
- Fixture stream: `conformance/adapters/claude/event-stream.json`.
- Fixture receipt: `conformance/adapters/claude/event-stream-receipt.json`.
- Validation command:

```bash
python3 tools/release/validate_adapter_event_guidance.py \
  --evidence work/event-guidance.json
```

The fixture is offline conformance evidence. It does not claim official
directory approval, production promotion or broader Claude Code host support.
