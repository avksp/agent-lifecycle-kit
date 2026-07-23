# Adapter support matrix

This matrix is the authoritative `v0.1.1` source-release support claim.
`EXPERIMENTAL` means the adapter has an offline projection and deterministic
contract tests. `VERIFIED` is reserved for a later production-promotion release
with bounded live install and lifecycle conformance evidence.

## Runtime support

| Host | Projection | Current maturity | Install/publication claim |
| --- | --- | --- | --- |
| Codex | Root `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` plus shared skills | EXPERIMENTAL | Tagged source marketplace manifest exists; public Plugins Directory review not claimed |
| Claude Code | Root `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` plus shared skills | EXPERIMENTAL | Tagged source marketplace manifest exists; official directory review not claimed |
| Cursor | Root `.cursor-plugin/plugin.json` and `.cursor-plugin/marketplace.json` plus shared skills | EXPERIMENTAL | Source projection exists for local/team validation and public submission; marketplace approval not claimed |
| Hermes | `skills.sh.json`, shared skills, and Hermes registry/slash-command projection metadata | EXPERIMENTAL | Direct skill install/tap metadata exists; live Hermes verification not claimed |
| OpenCode | Root `opencode.json`, shared skills, and JS adapter projection metadata | EXPERIMENTAL | Local source projection exists; npm package publication not claimed |

## Compact context support

The source release includes `profiles/small-context-profile.v1.json` and a
deterministic `context check/render` CLI for 4k-strict, 8k, 16k, 32k, and 64k
context windows. This is a core capability; adapters must pass the rendered
envelope to their host without silently expanding or truncating it. Compact-mode
support requires the core receipt to pass all profile budgets, including
reserved output, active packet, state summary, evidence summary, optional
`toolOutputs`, and recent verbatim user-turn count.

## Neutrality error contract

Neutrality CLI helpers return `agent-lifecycle-error.v1` with domain-specific
codes on fail-closed errors. Adapters should branch on `code`, not stderr text.
Generic `neutrality-contract-violation` is reserved for uncategorized defects
and should be treated as blocking.

## Production-promotion platform matrix

The production-promotion contract requires these external CI legs. The offline
source release validates that the contract is present; it does not claim the
legs were executed.

| Leg id | OS family | Architecture | Python |
| --- | --- | --- | --- |
| linux-py311 | Ubuntu 24.04 | x86_64 | 3.11 |
| linux-py312 | Ubuntu 24.04 | x86_64 | 3.12 |
| linux-py313 | Ubuntu 24.04 | x86_64 | 3.13 |
| macos-py311 | macOS 14 | arm64 | 3.11 |
| macos-py312 | macOS 14 | arm64 | 3.12 |
| macos-py313 | macOS 14 | arm64 | 3.13 |
| windows-py311 | Windows Server 2022 | x86_64 | 3.11 |
| windows-py312 | Windows Server 2022 | x86_64 | 3.12 |
| windows-py313 | Windows Server 2022 | x86_64 | 3.13 |
