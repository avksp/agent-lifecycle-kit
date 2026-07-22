# Adapter support matrix

This matrix is the authoritative release-candidate support claim. `EXPERIMENTAL`
means the adapter has an offline projection and deterministic contract tests.
`VERIFIED` is reserved for a later production-promotion release with bounded
live conformance evidence.

## Runtime support

| Host | Projection | Current maturity | Install claim |
| --- | --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` plus shared skills | EXPERIMENTAL | Release-candidate projection only |
| Claude Code | `.claude-plugin/plugin.json` plus shared skills | EXPERIMENTAL | Release-candidate projection only |
| Cursor | `.cursor-plugin/plugin.json` plus shared skills | EXPERIMENTAL | Release-candidate projection only |
| Hermes | Hermes registry/config projection plus shared skills | EXPERIMENTAL | Release-candidate projection only |
| OpenCode | `opencode.json` and JS adapter plus shared skills | EXPERIMENTAL | Release-candidate projection only |

## Compact context support

The release candidate includes `profiles/small-context-profile.v1.json` and a
deterministic `context check/render` CLI for 8k, 16k, 32k, and 64k context
windows. This is a core capability; adapters must pass the rendered envelope to
their host without silently expanding or truncating it.

## Production-promotion platform matrix

The production-promotion contract requires these external CI legs. The offline
candidate validates that the contract is present; it does not claim the legs
were executed.

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
