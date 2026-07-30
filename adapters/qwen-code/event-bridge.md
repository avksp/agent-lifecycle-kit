# Qwen Code event bridge

The Qwen Code projection uses Qwen Code `stream-json` output as the live host
receipt source. `adapters/qwen-code/runner.py` normalizes one bounded Qwen Code
invocation into `agent-host-operation-receipt.v1`; workflow-level lifecycle
events remain emitted by the Agent Lifecycle Kit controller.

This bridge intentionally does not claim a separate Qwen Code callback API. If a
future Qwen Code release exposes native lifecycle callbacks, this file is the
adapter-owned place to map those callbacks into `agent-adapter-event.v1`.
Unsupported or malformed host output must fail closed.
