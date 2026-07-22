# Universal distribution and README contract

## Decision

`agent-lifecycle-kit` is one versioned product and one repository, not one
host-specific manifest. The deterministic lifecycle core, schemas, CLI, five
canonical skills, fixtures and semantic conformance suite have one canonical
source. Release assembly projects that source into native bundles without
forking lifecycle semantics.

The first release has five required surface projections:

| Surface | Required native projection | Required activation proof |
| --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` and shared `skills/` | manifest validation, marketplace install, discovery, invocation and lifecycle canary |
| Claude Code | `.claude-plugin/plugin.json`, shared `skills/` and Claude host metadata | `claude plugin validate`, marketplace or `--plugin-dir` load, reload, namespaced skill invocation and lifecycle canary |
| Cursor | `.cursor-plugin/plugin.json`, shared `skills/` and Cursor host metadata | manifest validation, install/discovery, skill invocation and lifecycle canary on the declared host range |
| Hermes | shared skills plus Hermes skill-directory projection and optional Hermes plugin metadata | skill directory discovery, slash-command invocation, capability mapping and lifecycle canary |
| OpenCode | shared skills plus a JS/TS plugin adapter and explicit project/user or npm install projection | discovery through the native skill tool, plugin startup, capability mapping and lifecycle canary |

The three JSON plugin manifests are independent native adapters over the same
release identity. They are not aliases, symlinks or attempts to make one
vendor schema parse as another. OpenCode's plugin module and skill discovery
remain separate native concepts and are assembled together only by the
OpenCode release projection.

Additional hosts consume the public adapter contract and conformance suite.
They are not silently declared supported because they can read `SKILL.md`.

## Shared-core boundary

Adapters own only native discovery, installation metadata, invocation,
questions, approvals, native tasks/subagents, cancellation, usage import and
typed host-operation transport. They must not reimplement SDD, freeze,
compilation, workflow transitions, audit verdicts, context authority, budgets
or final proof.

Every generated bundle binds the same distribution version, source digest,
core contract inventory and canonical skill digests. A mismatch between any
surface projection and the canonical inventory rejects release assembly.

Offline conformance can promote a bundle only to `EXPERIMENTAL`. `VERIFIED`
requires fresh bounded live evidence for the exact host and adapter range.
Unsupported mandatory capabilities fail closed and must be visible in the
support matrix.

## Installation boundary

The repository does not silently change personal or team marketplace state.
Documentation may provide explicit native installation commands. Installers,
if added later, must support a preview/dry-run and require explicit authority
before changing host configuration.

Installation instructions may name only release artifacts and package names
that actually exist. Pre-release documentation must say that `main` is not
installable and must distinguish future commands from currently verified
commands.

## README contract

Root `README.md` is the canonical English user entry point. It must:

- link to `README.ru.md` near the title;
- explain the full lifecycle and the five canonical skills;
- explain one shared product with native host projections;
- give evidence-accurate installation and activation instructions for Codex,
  Claude Code, Cursor, Hermes and OpenCode;
- include a complete full-lifecycle usage prompt and stage-specific invocation
  guidance;
- explain authorization, automatic execution, durable state, maturity and
  fail-closed behavior;
- link to official host documentation and Apache-2.0;
- contain no origin-project path, identifier, fixture or private URL.

`README.ru.md` is a complete Russian user version, links back to `README.md`,
and must remain semantically equivalent for status, install commands, support
matrix, invocation, security and license. Generated documentation checks shall
verify links, required headings, host coverage, command parity, absence of
unresolved placeholders in a release, and the rule that no adapter is claimed
available before its artifact and conformance receipt exist.

## Current official format authorities

- Codex: `https://learn.chatgpt.com/docs/build-plugins`
- Claude Code: `https://code.claude.com/docs/en/plugins`
- Cursor: `https://cursor.com/docs/plugins` and the official
  `https://github.com/cursor/plugins` specification repository
- OpenCode skills: `https://opencode.ai/docs/skills/`
- OpenCode plugins: `https://opencode.ai/docs/plugins/`
- Hermes skills:
  `https://hermes-agent.nousresearch.com/docs/user-guide/features/skills`
- Hermes docs: `https://hermes-agent.nousresearch.com/docs/`

These URLs are discovery inputs, not frozen runtime authority. Release
conformance freezes the exact host range and locally validated schema or
manifest profile used for each adapter.
