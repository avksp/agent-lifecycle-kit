# Adapter support matrix

This matrix is the authoritative source-tree support claim. The source
distribution carries the support claims and evidence references below. The
source tree includes host-local model selection, budget-mode controls,
lifecycle gates, Claude Code live promotion evidence, Codex CLI live promotion
evidence, reusable promotion guidance, adapter capability manifests, safe
adapter inspection, and ordered terminal outcomes for OpenCode, Hermes, Cursor,
Gemini CLI, qwen-code, and Kimi Code.
`EXPERIMENTAL` means the adapter has an offline projection and deterministic
contract tests. `VERIFIED` is host-specific and requires bounded live host
conformance, live calibration, and lifecycle proof evidence.

## Runtime support

| Host | Projection | Current maturity | Install/publication claim |
| --- | --- | --- | --- |
| Codex | Root `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` plus shared skills | VERIFIED | Codex CLI 0.145.0 live host conformance, live calibration, and ALK lifecycle proof passed locally; public Plugins Directory review not claimed |
| Claude Code | Root `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` plus shared skills | VERIFIED | Claude Code 2.1.220 live host conformance, live calibration, and ALK lifecycle proof passed locally; official directory review not claimed |
| Cursor | Root `.cursor-plugin/plugin.json` and `.cursor-plugin/marketplace.json` plus shared skills and capability manifest | EXPERIMENTAL | Cursor Agent 2026.07.23-e383d2b safe inspection passed on local Free tier; bounded smoke cannot promote without usage/cost calibration and lifecycle proof; marketplace approval not claimed |
| Gemini CLI | Host-local projection, bounded runner, live harness and capability manifest | EXPERIMENTAL | Gemini CLI 0.46.0 safe inspection and bounded harness shape passed; local live canary is blocked by unsupported Gemini Code Assist client tier; live receipts, usage calibration, lifecycle proof, and publication not claimed |
| Hermes | `skills.sh.json`, shared skills, Hermes registry/slash-command projection metadata, and capability manifest | VERIFIED | Hermes Agent v0.19.0 live host conformance, live calibration, and ALK lifecycle proof passed locally; official directory/publication review not claimed |
| Kimi Code | Host-local projection, bounded runner, live harness and capability manifest | EXPERIMENTAL | Kimi Code 0.30.0 safe inspection and bounded harness shape passed; local live canary is blocked until a provider/model alias is configured; live receipts, usage calibration, lifecycle proof, and publication not claimed |
| OpenCode | Root `opencode.json`, shared skills, JS adapter projection metadata, and capability manifest | VERIFIED | OpenCode CLI 1.18.9 live host conformance, live calibration, and ALK lifecycle proof passed locally; npm publication not claimed |
| qwen-code | Host-local qwen CLI runner, source projection, and capability manifest | VERIFIED | qwen-code 0.21.0 live host conformance, live calibration, and ALK lifecycle proof passed on GLM 5.2 locally; public package approval not claimed |

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

Codex is `VERIFIED` for host-local model routing on Codex CLI 0.145.0. Claude
Code is `VERIFIED` for host-local model routing on Claude Code 2.1.220.
OpenCode is `VERIFIED` for host-local model routing on OpenCode CLI 1.18.9.
Hermes is `VERIFIED` for host-local model routing on Hermes Agent v0.19.0.
qwen-code is `VERIFIED` for host-local model routing on qwen-code 0.21.0.
Their live receipts include host usage attestation, quality pass status, and
bounded budget evidence. Cursor, Gemini CLI, and Kimi Code remain
`EXPERIMENTAL`: Cursor declares fail-closed support for host-local model
profiles and model-route execution, while Gemini CLI and Kimi Code have bounded
runners/harnesses but still need accepted live usage receipts and quality/cost
evidence before a host-specific `VERIFIED` claim. On the current local host,
Gemini CLI is blocked by an unsupported Gemini Code Assist client tier and Kimi
Code is blocked by missing provider/model configuration.

`agent-lifecycle adapter scaffold` creates descriptor, capability manifest,
fail-closed runner, receipt-normalizer, conformance and documentation
skeletons for new host projections. The scaffold is limited to `EXPERIMENTAL`
metadata and cannot create `VERIFIED`, production-promotion, or concrete
provider-model claims. `agent-lifecycle adapter inspect` records descriptor and
safe host capability discovery; inspection evidence is not a live conformance
receipt and does not promote support on its own.
`agent-lifecycle diagnose` composes these checks into one redacted readiness
report, and `agent-lifecycle adapter install-plan` previews host-local setup
without writing configuration or changing maturity labels.

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

## Codex CLI 0.6.0 live evidence

Codex is verified only for the tested local host range:

- Host: Codex CLI 0.145.0.
- Source revision: `b01a1793e42f52e20077a7aa26b8e4e25c3bd216`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/codex-cli-0.6.0.md`.
- Live preflight:
  `tasks/release-0-6/evidence/codex-live-promotion/preflight/codex-preflight-report.json`.
- Live host conformance receipt:
  `tasks/release-0-6/evidence/codex-live-promotion/live-host-receipts/codex.json`.
- Live host conformance validation:
  `tasks/release-0-6/evidence/codex-live-promotion/live-host-conformance-codex.json`.
- Live calibration receipt:
  `tasks/release-0-6/evidence/codex-live-promotion/live-calibration-receipts/codex.json`.
- Live calibration validation:
  `tasks/release-0-6/evidence/codex-live-promotion/live-calibration-verification-codex.json`.
- ALK lifecycle final proof:
  `tasks/release-0-6/evidence/codex-live-promotion/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, or a broader production-promotion platform matrix pass.

## Claude Code 0.5.0 live evidence

Claude Code is verified only for the tested local host range:

- Host: Claude Code 2.1.220.
- Source revision: `6bb3b58ee01d028fe21cef209c284efc79e55ceb`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/claude-code-0.5.0.md`.
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

## OpenCode GLM 5.2 live evidence

OpenCode is verified only for the tested local host range:

- Host: OpenCode CLI 1.18.9.
- Source revision: `6c6b40210ee28de4b6a5993367af89e629fb99ff`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/opencode-glm52-live-2026-07-29.md`.
- Live preflight:
  `tasks/release-0-7/evidence/opencode/preflight/opencode-glm52-preflight-report.json`.
- Live host conformance receipt:
  `tasks/release-0-7/evidence/opencode/live-host-receipts/opencode.json`.
- Live host conformance validation:
  `tasks/release-0-7/evidence/opencode/live-host-conformance-opencode.json`.
- Live calibration receipt:
  `tasks/release-0-7/evidence/opencode/live-calibration-receipts/opencode.json`.
- Live calibration validation:
  `tasks/release-0-7/evidence/opencode/live-calibration-verification-opencode.json`.
- ALK lifecycle final proof:
  `tasks/release-0-7/evidence/opencode/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, npm publication, public
directory approval, or a broader production-promotion platform matrix pass.

## Hermes GLM 5.2 live evidence

Hermes is verified only for the tested local host range:

- Host: Hermes Agent v0.19.0.
- Source revision: `d71033a4`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/hermes-glm52-live-2026-07-29.md`.
- Live preflight:
  `tasks/release-0-8/evidence/hermes/preflight/hermes-glm52-preflight-report.json`.
- Live host conformance receipt:
  `tasks/release-0-8/evidence/hermes/live-host-receipts/hermes.json`.
- Live host conformance validation:
  `tasks/release-0-8/evidence/hermes/live-host-conformance-hermes.json`.
- Live calibration receipt:
  `tasks/release-0-8/evidence/hermes/live-calibration-receipts/hermes.json`.
- Live calibration validation:
  `tasks/release-0-8/evidence/hermes/live-calibration-verification-hermes.json`.
- ALK lifecycle final proof:
  `tasks/release-0-8/evidence/hermes/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, or a broader production-promotion platform matrix pass.

## qwen-code GLM 5.2 live evidence

qwen-code is verified only for the tested local host range:

- Host: qwen-code 0.21.0.
- Source revision: `6c6b40210ee28de4b6a5993367af89e629fb99ff`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/qwen-code-glm52-live-2026-07-29.md`.
- Live preflight:
  `tasks/release-0-11/evidence/qwen-code/live-preflight/qwen-code-preflight-report.json`.
- Live host conformance receipt:
  `tasks/release-0-11/evidence/qwen-code/live-host-receipts/qwen-code.json`.
- Live host conformance validation:
  `tasks/release-0-11/evidence/qwen-code/live-host-conformance-qwen-code.json`.
- Live calibration receipt:
  `tasks/release-0-11/evidence/qwen-code/live-calibration-receipts/qwen-code.json`.
- Live calibration validation:
  `tasks/release-0-11/evidence/qwen-code/live-calibration-verification-qwen-code.json`.
- ALK lifecycle final proof:
  `tasks/release-0-11/evidence/qwen-code/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public package
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
