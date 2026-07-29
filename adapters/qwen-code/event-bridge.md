# qwen-code event bridge

The qwen-code projection uses qwen `stream-json` output as the live host
receipt source. `adapters/qwen-code/runner.py` normalizes one bounded qwen
invocation into `agent-host-operation-receipt.v1`; workflow-level lifecycle
events remain emitted by the Agent Lifecycle Kit controller.

This bridge intentionally does not claim a separate qwen callback API. If a
future qwen release exposes native lifecycle callbacks, this file is the
adapter-owned place to map those callbacks into `agent-adapter-event.v1`.
Unsupported or malformed host output must fail closed.
