# Grok Build adapter

ACP is declared behind a required local probe. A failed probe still leaves operations fail-closed.

Maturity is host-specific `VERIFIED` for Grok Build `0.2.117` on the tested
local `grok-4.5` binding. The live harness uses single-turn JSON output,
disabled subagents/memory/web search, plan permission mode, an empty tools
allowlist and post-invocation clean-worktree checks. Unsupported operations
fail closed and lifecycle semantics stay delegated to ALK core.
