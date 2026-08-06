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
| Agent runtimes | Omnigent, OpenHands, Archon | Launch agents, coordinate workflows, often provide UI/server/runtime | ALK keeps provider execution outside the portable core. Managed launch is descriptor-declared, not a provider broker. |
| Specification tools | OpenSpec, GitHub Spec Kit, BMAD-METHOD, Spec Kitty | Describe what should be built | ALK can import those materials as reviewed drafts; the frozen ALK plan remains authoritative. |
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

## What ALK includes

ALK also includes these optional capabilities:

- managed adapter sessions and task intake accept task text, Markdown files and
  frozen run requests while keeping host launch policy in adapter descriptors;
  bundled adapter descriptors currently declare `WRAPPER_ONLY` for managed
  launch;
- imported OpenSpec, Spec Kit, BMAD, Spec Kitty and related materials remain
  reviewed draft input until an ALK plan is frozen;
- optional Review Mesh creates reviewer assignments, imports redacted results,
  synthesizes findings and checks quorum only when a frozen plan opts in;
- adapter event capture, external memory context, read-only goal/progress views
  and Bug Forensics advisory receipts add evidence without making ALK a model
  broker or memory database.

## Named examples

| Project | Similarity to ALK | Main difference |
| --- | --- | --- |
| oh-my-openagent | Improves long agent work with host-level skills, modes and team workflows. | It goes deeper into the host harness and agent runtime; ALK stays outside as a portable lifecycle and evidence layer. |
| bmad-loop | Closest deterministic-loop neighbor: it emphasizes non-LLM control flow, verification and resumable work. | It runs host CLIs through its own loop; ALK keeps host execution at the adapter or wrapper boundary and covers the full spec-to-proof lifecycle. |
| goalbuddy | Similar goal continuity and visible proof-loop intent. | It is a lighter goal-board workflow; ALK adds SDD, freeze, ownership, audit, adapters, optional multi-review and final proof. |

## Where ALK can be unnecessary

ALK can be too much for a small one-off edit.

## Integration model

| External layer | How it can work with ALK |
| --- | --- |
| OpenSpec, Spec Kit, BMAD and Spec Kitty documents | Import as draft input, then review and freeze an ALK plan. |
| Codex, Claude Code, Cursor, Gemini CLI, Goose, Grok Build, Hermes, Kimi Code, OpenCode, OpenInterpreter, Pi, Qwen Code | Use as host executors through adapters and host-local profiles; current bundled descriptors are `WRAPPER_ONLY` for managed launch. |
| SWE-agent or another code agent | Treat as an external executor whose output still needs ALK evidence. |
| Agent runtimes or web UIs | Keep launch, UI and collaboration outside core; import receipts or results. |
| Memory systems | Import redacted context with citations, source digests and no proof authority. |
| Skill libraries | Reuse as guidance, then bind actual work to ALK contracts and gates. |

## Main boundary

ALK should stay a verifiable completion layer. It may accept drafts, show
progress, prepare reviewer assignments and validate evidence, but it should not
become a model broker, a required web UI, a knowledge base, a second workflow
runtime, or an automatic adapter-promotion tool.
