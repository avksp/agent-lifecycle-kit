# Adapter support matrix

This matrix is the authoritative current source-tree support claim. `v0.4.0`
remains the latest tagged source release, while the local `0.5.x` line adds
host-local model selection, budget-mode controls, and Claude Code live
promotion evidence. `EXPERIMENTAL` means the adapter has an offline projection
and deterministic contract tests. `VERIFIED` is host-specific and requires
bounded live host conformance, live calibration, and lifecycle proof evidence.

## Runtime support

| Host | Projection | Current maturity | Install/publication claim |
| --- | --- | --- | --- |
| Codex | Root `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` plus shared skills | EXPERIMENTAL | Tagged source marketplace manifest exists; public Plugins Directory review not claimed |
| Claude Code | Root `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` plus shared skills | VERIFIED | Claude Code 2.1.220 live host conformance, live calibration, and ALK lifecycle proof passed locally; official directory review not claimed |
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

Production-promotion claims require two host-bound evidence tracks. Lifecycle
operation coverage is checked by
`tools/release/validate_live_host_conformance.py` against
`conformance/core/adapter-baseline.v1.json`; cost and usage coverage is checked
by `tools/release/validate_live_calibration.py` against
`conformance/core/live-calibration-profile.v1.json` and
`conformance/core/budget-targets.v1.json`. A promoted host needs one passing
live host conformance receipt and one passing live calibration receipt.
Synthetic replay baselines remain offline regression fixtures only and cannot
promote an adapter from `EXPERIMENTAL` to `VERIFIED`.

## Model routing support

The core includes provider-neutral model routing through `agent-lifecycle model
profile-check`, `agent-lifecycle model route`, `agent-lifecycle model
usage-check`, and workflow-level usage-receipt enforcement on `workflow
task-result`. Adapters map neutral classes to concrete host/runtime models
through host-local `agent-host-model-selection-profile.v1` files, with the
older `agent-lifecycle-host-model-profile.v1` shape kept for compatibility.
Concrete provider model names must not appear in portable core contracts; live
harnesses write `agent-host-model-selection-receipt.v1` with redacted binding
hashes.

Claude Code is `VERIFIED` for host-local model routing on Claude Code 2.1.220:
the live receipts include host usage attestation, quality pass status, and
budget evidence for the `0.5.1` promotion patch.
Codex, Cursor, Hermes, and OpenCode remain `EXPERIMENTAL`: they declare
fail-closed support for host-local model profiles and model-route execution,
but still need live usage receipts and quality/cost evidence before a
host-specific `VERIFIED` claim.

`agent-lifecycle adapter scaffold` may create new host projection skeletons, but
the scaffold is limited to `EXPERIMENTAL` metadata and cannot create
`VERIFIED`, production-promotion, or concrete provider-model claims.

Critical review phases must not silently downgrade to `budget` or
`local-compact`. A local-only host can satisfy final/security/performance review
only with an explicit `local-strong-review` or equivalent review-capable binding
that passes context, tool-use, JSON, usage-attestation and live-calibration
gates.

Budget routing supports `metered`, `subscription`, and `local` modes. Metered
mode requires a USD cap; subscription and local modes require invocation caps
plus token and/or wall-clock caps. Exceeding a cap pauses for an operator
decision or follows a bounded auto-reroute policy, but it never upgrades an
adapter to `VERIFIED` by itself.

## Claude Code 0.5.1 live evidence

Claude Code is verified only for the tested local host range:

- Host: Claude Code 2.1.220.
- Source revision: `6bb3b58ee01d028fe21cef209c284efc79e55ceb`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/claude-code-0.5.1.md`.
- Plan validation:
  `tasks/release-0-5/evidence/0.5.1-claude-live-promotion/live-host-promotion-plan-validation.json`.
- Live preflight:
  `tasks/release-0-5/evidence/0.5.1-claude-live-promotion/preflight/claude-code-preflight-report.json`.
- Live host conformance receipt:
  `tasks/release-0-5/evidence/live-host-receipts/claude-code.json`.
- Live host conformance validation:
  `tasks/release-0-5/evidence/live-host-conformance-claude-code.json`.
- Live calibration receipt:
  `tasks/release-0-5/evidence/live-calibration/claude-code.json`.
- Live calibration validation:
  `tasks/release-0-5/evidence/live-calibration-verification-claude-code.json`.
- ALK lifecycle final proof:
  `tasks/release-0-5/evidence/0.5.1-claude-live-promotion/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, or a broader production-promotion platform matrix pass.

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
