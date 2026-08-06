# Project comparison

Agent Lifecycle Kit is a lifecycle controller for coding-agent work. It is not
a coding agent, not a runtime, not a model broker, and not a memory database.
It keeps the task lifecycle explicit: draft intake, reviewed specification,
frozen plan, bounded work, implementation audit, and final proof.

Source of truth remains the frozen ALK plan. External specifications, skills,
memories, agent runtimes and code agents can help, but they enter ALK as draft
input, host-owned execution, or optional context.

## Short version

| Project class | Examples | What they solve | ALK boundary |
| --- | --- | --- | --- |
| Coding agents | SWE-agent, Aider, Cline, Continue | Edit code and run tests | ALK does not edit code by itself; it controls plan, evidence and final proof around an executor. |
| Agent runtimes | Omnigent, OpenHands, Archon | Launch agents, coordinate workflows, often provide UI/server/runtime | ALK keeps host launch outside the portable core and does not require a daemon or database. |
| Specification tools | OpenSpec, GitHub Spec Kit, BMAD-METHOD | Describe what should be built | ALK can import those materials as reviewed drafts; the frozen ALK plan remains authoritative. |
| Skill and method libraries | superpowers, AGENTS.md, agent-skills | Guide agent behavior through instructions | ALK adds machine-checkable contracts, locks, receipts and gates. |
| Memory systems | gbrain, mem0, zep | Retrieve long-term context and knowledge | ALK can use external memory as redacted context, not as proof or source of truth. |

## Where ALK fits best

ALK is useful when the team wants to:

- keep one delivery process while switching CLI or model;
- prove that a task is complete, not only that a patch was produced;
- preserve write boundaries, acceptance criteria and evidence;
- use small or local models with compact task packets and deterministic checks;
- coordinate optional multi-review without making the core a provider broker;
- continue long tasks across sessions without losing plan and evidence state.

## Where ALK can be unnecessary

ALK can be too much when the task is a one-off small edit, an exploratory chat,
or a workflow that does not need stored plans, audit gates or final proof.

## Integration model

| External layer | How it can work with ALK |
| --- | --- |
| OpenSpec, Spec Kit, BMAD documents | Import as draft input, then review and freeze an ALK plan. |
| Codex, Claude Code, OpenCode, Goose, Pi, Qwen Code | Use as host executors through adapters and host-local profiles. |
| SWE-agent or another code agent | Treat as an external executor whose output still needs ALK evidence. |
| Agent runtimes or web UIs | Keep launch, UI and collaboration outside core; import receipts or results. |
| Memory systems | Import redacted context with citations, source digests and no proof authority. |
| Skill libraries | Reuse as guidance, then bind actual work to ALK contracts and gates. |

## Main boundary

ALK should stay a verifiable completion layer. It may accept drafts, show
progress, prepare reviewer assignments and validate evidence, but it should not
become a model broker, a required web UI, a knowledge base, a second workflow
runtime, or an automatic adapter-promotion tool.
