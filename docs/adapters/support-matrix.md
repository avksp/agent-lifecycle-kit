# Adapter support matrix

This matrix is the authoritative `v0.1.2` source-release support claim.
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

The conformance corpus includes both `S1-SMALL-CONTEXT-4K-STRICT-01` and
`S1-SMALL-CONTEXT-8K-01`. A host that claims compact-context support must pass
the explicit `4k-strict` path rather than treating 8k behavior as proof for
sub-8k local models.

## Live cost calibration support

Production-promotion cost claims require a live, usage-attested receipt checked
by `tools/release/validate_live_calibration.py` against
`conformance/core/live-calibration-profile.v1.json` and
`conformance/core/budget-targets.v1.json`. Synthetic replay baselines remain
offline regression fixtures only and cannot promote an adapter from
`EXPERIMENTAL` to `VERIFIED`.

## Model routing support

The core includes provider-neutral model routing through `agent-lifecycle model
profile-check`, `agent-lifecycle model route`, `agent-lifecycle model
usage-check`, and workflow-level usage-receipt enforcement on `workflow
task-result`. Adapters map neutral classes to concrete host/runtime models
through host-local
`agent-lifecycle-host-model-profile.v1` files. Concrete provider model names
must not appear in portable core contracts.

All current adapters remain `EXPERIMENTAL`: they declare fail-closed support
for host-local model profiles and model-route execution, but no adapter is
`VERIFIED` for model routing until it has live usage receipts and quality/cost
evidence.

Critical review phases must not silently downgrade to `budget` or
`local-compact`. A local-only host can satisfy final/security/performance review
only with an explicit `local-strong-review` or equivalent review-capable binding
that passes context, tool-use, JSON, usage-attestation and live-calibration
gates.

## Neutrality error contract

Neutrality CLI helpers return `agent-lifecycle-error.v1` with domain-specific
codes on fail-closed errors. Adapters should branch on `code`, not stderr text.
Generic `neutrality-contract-violation` is reserved for uncategorized defects
and should be treated as blocking.

## Neutrality archive policy

The default neutrality policy declares ZIP archive limits for nesting depth,
archives per subject, entries per archive, entries per subject, compressed bytes
per archive, expanded bytes per archive, expanded bytes per entry, expanded
bytes per subject, and compression ratio. The scanner enforces these limits
fail-closed through the `archiveLimitBreaches` counter. Unsupported archive
formats are counted as `unsupportedArchives`.

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
