# Adapter support matrix

This matrix is the authoritative source-tree support claim. The source
distribution carries the support claims and evidence references below. The
source tree includes host-local model selection, budget-mode controls,
lifecycle gates, Claude Code live promotion evidence, Codex CLI live promotion
evidence, reusable promotion guidance, adapter capability manifests, safe
adapter inspection, and ordered terminal outcomes for OpenCode, Hermes, Cursor,
Gemini CLI, Goose, Qwen Code, Kimi Code, Grok Build, OpenInterpreter, and Pi.
`EXPERIMENTAL` means the adapter has an offline projection and deterministic
contract tests. `VERIFIED` is host-specific and requires bounded live host
conformance, live calibration, and lifecycle proof evidence.

Public contract compatibility is checked through
`agent-public-contract-policy.v1`. That policy stabilizes schema ids, accepted
deprecated inputs, CLI JSON envelopes and error codes. It does not promote an
adapter by itself.

Managed session support is documented separately from maturity. Current bundled
adapters declare `managedLaunch.status: WRAPPER_ONLY`: ALK can bind lifecycle
proof through managed commands or wrappers, but it does not claim safe native
argv launch. See [Managed adapter session support](managed-session-support.md).
Every generic descriptor-driven launch request is blocked with
`adapter-generic-launch-disabled` before a host process is created; a descriptor
status cannot bypass that boundary.

An operator may separately opt into the validated local profile route under
`.alk/host-launch/`. That route requires frozen and risk bindings and produces
a local receipt, but it does not change any row below. See [Local host
launch](../reference/local-host-launch.md).

Exact-version local launch profiles are qualified for Codex `0.147.0`, Claude
Code `2.1.226` and OpenCode `1.18.15`. They require a matching preflight
receipt and preserve `WRAPPER_ONLY`; see [Qualified host
launch](../reference/qualified-host-launch.md).

Host-local token normalization is a separate claim. Claude Code, Codex, Gemini
CLI, Kimi Code, OpenCode and Qwen Code declare
`usageNormalization.status: FIXTURE_ONLY`; their bounded
parsers are tested, but their sidecars do not satisfy S1/S2 usage gates. Other
bundled descriptors have no declaration and are treated as `UNSUPPORTED` by
this contract. Qwen Code's adapter maturity remains `VERIFIED`; that does not
implicitly qualify the newly factored parser. See
[Host-local token accounting](../reference/host-local-token-accounting.md).

## Runtime support

| Host | Projection | Current maturity | Managed launch | Install/publication claim |
| --- | --- | --- | --- | --- |
| Codex | Root `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` plus shared skills | VERIFIED | `WRAPPER_ONLY` | Codex CLI 0.145.0 live host conformance, live calibration, and ALK lifecycle proof passed locally; public Plugins Directory review not claimed |
| Claude Code | Root `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` plus shared skills | VERIFIED | `WRAPPER_ONLY` | Claude Code 2.1.220 live host conformance, live calibration, and ALK lifecycle proof passed locally; official directory review not claimed |
| Cursor | Root `.cursor-plugin/plugin.json` and `.cursor-plugin/marketplace.json` plus shared skills and capability manifest | EXPERIMENTAL | `WRAPPER_ONLY` | Cursor Agent 2026.07.23-e383d2b safe inspection passed on local Free tier; bounded smoke cannot promote without usage/resource calibration and lifecycle proof; marketplace approval not claimed |
| Gemini CLI | Host-local projection, bounded runner, live harness and capability manifest | EXPERIMENTAL | `WRAPPER_ONLY` | Gemini CLI 0.46.0 safe inspection and bounded harness shape passed; local live canary is blocked by unsupported Gemini Code Assist client tier; live receipts, usage calibration, lifecycle proof, and publication not claimed |
| Goose | ACP host-capability projection, bounded no-profile live harness, and capability manifest | VERIFIED | `WRAPPER_ONLY` | Goose 1.45.0 live host conformance, live calibration, and ALK lifecycle proof passed locally on a host-local provider/model binding; public directory approval not claimed |
| Grok Build | ACP probe-gated CLI projection, bounded plan-mode live harness and capability manifest | VERIFIED | `WRAPPER_ONLY` | Grok Build 0.2.117 live host conformance, live calibration, ACP probe and ALK lifecycle proof passed locally on a host-local provider/model binding; public directory approval not claimed |
| Hermes | `skills.sh.json`, shared skills, Hermes registry/slash-command projection metadata, and capability manifest | VERIFIED | `WRAPPER_ONLY` | Hermes Agent v0.19.0 live host conformance, live calibration, and ALK lifecycle proof passed locally; official directory/publication review not claimed |
| Kimi Code | Host-local projection, bounded runner, live harness and capability manifest | EXPERIMENTAL | `WRAPPER_ONLY` | Kimi Code 0.30.0 safe inspection and bounded harness shape passed; local live canary is blocked until a provider/model alias is configured; live receipts, usage calibration, lifecycle proof, and publication not claimed |
| OpenCode | Root `opencode.json`, shared skills, JS adapter projection metadata, and capability manifest | VERIFIED | `WRAPPER_ONLY` | OpenCode CLI 1.18.9 live host conformance, live calibration, and ALK lifecycle proof passed locally; npm publication not claimed |
| OpenInterpreter | Host-local compatible CLI projection, bounded JSONL live harness and capability manifest | VERIFIED | `WRAPPER_ONLY` | `interpreter` 0.0.34 live host conformance, live calibration, containment and ALK lifecycle proof passed locally on a host-local provider/model binding; public directory approval not claimed |
| Pi | RPC/JSON plus AGENTS/agentskills projection, bounded JSONL live harness and capability manifest | VERIFIED | `WRAPPER_ONLY` | Pi 0.83.0 live host conformance, live calibration, containment, host-env hygiene and ALK lifecycle proof passed locally on a host-local provider/model binding; public directory approval not claimed |
| Qwen Code | Host-local qwen CLI runner, source projection, and capability manifest | VERIFIED | `WRAPPER_ONLY` | Qwen Code 0.21.0 live host conformance, live calibration, and ALK lifecycle proof passed on a host-local provider/model binding; public package approval not claimed |

## Event capture support

Current adapter descriptors and capability manifests declare
`adapter-event-stream` with the portable `agent-adapter-event.v1` schema.
Offline conformance checks require `agent-adapter-event-stream-receipt.v1`
fixtures that bind event stream digests to descriptor digests. This is an
evidence-quality contract and does not change adapter maturity or claim
production promotion.

No automatic hook installation: event capture is `adapter-owned`. ALK core does
not install native host hooks, write host configuration or parse raw host
telemetry. The per-adapter native hook, wrapper route, receipt route and
automatic-hook claim status are documented in
[Adapter event capture matrix](event-capture-matrix.md).

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

Adapter capability bench evidence is a drift detector for the live conformance
path. `generate_adapter_probe_plan.py` reads
`agent-adapter-capability-manifest.v1` files and emits a bounded declarative
plan with `liveCallsStarted: false`, `promotionDecision: NOT_EVALUATED` and no
maturity change claim. `validate_adapter_probe_evidence.py` compares live host
receipts to that plan and fails on missing planned operations, synthetic replay
for live-required operations or host-protocol envelope bypass. Passing bench
evidence is useful for promotion review, but it never promotes an adapter
without live conformance, calibration and lifecycle proof.

Sandbox evidence uses only `agent-sandbox-receipt.v1`. Partial process-tree
containment and credential proxy boundaries are expressed as receipt details;
secret values and private env-file paths are invalid receipt contents.

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
Qwen Code is `VERIFIED` for host-local model routing on Qwen Code 0.21.0.
Goose is `VERIFIED` for host-local model routing on Goose 1.45.0. Grok Build is
`VERIFIED` for host-local model routing on Grok Build 0.2.117. OpenInterpreter
is `VERIFIED` for host-local model routing on `interpreter` 0.0.34. Pi is
`VERIFIED` for host-local model routing on Pi 0.83.0. The verified adapters'
live receipts include host usage attestation, quality pass status, and bounded
budget evidence. Cursor, Gemini CLI and Kimi Code remain `EXPERIMENTAL`: Cursor
declares fail-closed support for host-local model profiles and model-route
execution, while Gemini CLI and Kimi Code have bounded runners/harnesses. These
adapters still need accepted live usage receipts, quality/resource evidence and
a concrete live host range before a host-specific `VERIFIED` claim. On the
current local host, Gemini CLI is blocked by an unsupported Gemini Code Assist
client tier, and Kimi Code is blocked by missing provider/model configuration.
Provider-flexible adapters must use the selected host/provider's configured or
documented env-key name rather than an ALK hardcoded secret name.

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

The redacted evidence summary index is tracked at
`docs/adapters/evidence/adapter-evidence-summary.v1.json`. It records which
summary file supports each source-tree maturity claim. Raw live receipts remain
host-local and ignored; their absence is a re-review concern, not the same
condition as a missing tracked summary.

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

Provider-flexible adapters must keep provider credentials host-local. The host
or selected provider determines the env-key name through its config or
documentation; ALK does not hardcode provider secret names. Live harnesses can
scope an operator env file to one invocation through `--host-env-file` plus an
explicit `--host-env-allow <NAME>`, and the related evidence must pass
`validate_host_env_hygiene.py` before promotion evidence is accepted.

Lifecycle cost reports add one more resource check: they separate
implementation, product validation, pipeline compliance and coordination cost.
This makes it visible when lifecycle checks are consuming more than the chosen
task mode allows. Cost accounting is not adapter maturity evidence; it is a
resource-control receipt for the run.

## Codex CLI 0.6.0 live evidence

Codex is verified only for the tested local host range:

- Host: Codex CLI 0.145.0.
- Source revision: `b01a1793e42f52e20077a7aa26b8e4e25c3bd216`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/codex-cli-0.6.0.md`.
- Live preflight:
  `work/release-0-6/evidence/codex-live-promotion/preflight/codex-preflight-report.json`.
- Live host conformance receipt:
  `work/release-0-6/evidence/codex-live-promotion/live-host-receipts/codex.json`.
- Live host conformance validation:
  `work/release-0-6/evidence/codex-live-promotion/live-host-conformance-codex.json`.
- Live calibration receipt:
  `work/release-0-6/evidence/codex-live-promotion/live-calibration-receipts/codex.json`.
- Live calibration validation:
  `work/release-0-6/evidence/codex-live-promotion/live-calibration-verification-codex.json`.
- ALK lifecycle final proof:
  `work/release-0-6/evidence/codex-live-promotion/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, or a broader production-promotion platform matrix pass.

## Claude Code 0.5.0 live evidence

Claude Code is verified only for the tested local host range:

- Host: Claude Code 2.1.220.
- Source revision: `6bb3b58ee01d028fe21cef209c284efc79e55ceb`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/claude-code-0.5.0.md`.
- Plan validation:
  `work/release-0-5/evidence/0.5.1-claude-live-promotion/live-host-promotion-plan-validation.json`.
- Live preflight:
  `work/release-0-5/evidence/0.5.1-claude-live-promotion/preflight/claude-code-preflight-report.json`.
- Live host conformance receipt:
  `work/release-0-5/evidence/live-host-receipts/claude-code.json`.
- Live host conformance validation:
  `work/release-0-5/evidence/live-host-conformance-claude-code.json`.
- Live calibration receipt:
  `work/release-0-5/evidence/live-calibration/claude-code.json`.
- Live calibration validation:
  `work/release-0-5/evidence/live-calibration-verification-claude-code.json`.
- ALK lifecycle final proof:
  `work/release-0-5/evidence/0.5.1-claude-live-promotion/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, or a broader production-promotion platform matrix pass.

## OpenCode Host-Local Live Evidence

OpenCode is verified only for the tested local host range:

- Host: OpenCode CLI 1.18.9.
- Source revision: `6c6b40210ee28de4b6a5993367af89e629fb99ff`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/opencode-host-local-live-2026-07-29.md`.
- Live preflight:
  host-local preflight receipt retained under ignored `work/` evidence.
- Live host conformance receipt:
  `work/release-0-7/evidence/opencode/live-host-receipts/opencode.json`.
- Live host conformance validation:
  `work/release-0-7/evidence/opencode/live-host-conformance-opencode.json`.
- Live calibration receipt:
  `work/release-0-7/evidence/opencode/live-calibration-receipts/opencode.json`.
- Live calibration validation:
  `work/release-0-7/evidence/opencode/live-calibration-verification-opencode.json`.
- ALK lifecycle final proof:
  `work/release-0-7/evidence/opencode/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, npm publication, public
directory approval, or a broader production-promotion platform matrix pass.

## Hermes Host-Local Live Evidence

Hermes is verified only for the tested local host range:

- Host: Hermes Agent v0.19.0.
- Source revision: `d71033a4`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/hermes-host-local-live-2026-07-29.md`.
- Live preflight:
  host-local preflight receipt retained under ignored `work/` evidence.
- Live host conformance receipt:
  `work/release-0-8/evidence/hermes/live-host-receipts/hermes.json`.
- Live host conformance validation:
  `work/release-0-8/evidence/hermes/live-host-conformance-hermes.json`.
- Live calibration receipt:
  `work/release-0-8/evidence/hermes/live-calibration-receipts/hermes.json`.
- Live calibration validation:
  `work/release-0-8/evidence/hermes/live-calibration-verification-hermes.json`.
- ALK lifecycle final proof:
  `work/release-0-8/evidence/hermes/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, or a broader production-promotion platform matrix pass.

## Qwen Code Host-Local Live Evidence

Qwen Code is verified only for the tested local host range:

- Host: Qwen Code 0.21.0.
- Source revision: `6c6b40210ee28de4b6a5993367af89e629fb99ff`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/qwen-code-host-local-live-2026-07-29.md`.
- Live preflight:
  `work/release-0-11/evidence/qwen-code/live-preflight/qwen-code-preflight-report.json`.
- Live host conformance receipt:
  `work/release-0-11/evidence/qwen-code/live-host-receipts/qwen-code.json`.
- Live host conformance validation:
  `work/release-0-11/evidence/qwen-code/live-host-conformance-qwen-code.json`.
- Live calibration receipt:
  `work/release-0-11/evidence/qwen-code/live-calibration-receipts/qwen-code.json`.
- Live calibration validation:
  `work/release-0-11/evidence/qwen-code/live-calibration-verification-qwen-code.json`.
- ALK lifecycle final proof:
  `work/release-0-11/evidence/qwen-code/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public package
approval, or a broader production-promotion platform matrix pass.

## Goose Host-Local Live Evidence

Goose is verified only for the tested local host range:

- Host: Goose 1.45.0.
- Source revision:
  `87fb1ce58612efbd2121d8eb56f9d54de8fbbcfb`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/goose-live-verified.md`.
- Live preflight:
  `work/release-1-16/evidence/preflight/goose-preflight-report.json`.
- Bounded containment receipt:
  `work/release-1-16/evidence/goose-containment-receipt.json`.
- Live host conformance receipt:
  `work/release-1-16/evidence/live-host-receipts/goose.json`.
- Live host conformance validation:
  `work/release-1-16/evidence/live-host-conformance-goose.json`.
- Live calibration receipt:
  `work/release-1-16/evidence/live-calibration-receipts/goose.json`.
- Live calibration validation:
  `work/release-1-16/evidence/live-calibration-verification-goose.json`.
- ALK lifecycle final proof:
  `work/release-1-16/evidence/goose/full-lifecycle/final/final-proof-r5.json`.

This evidence does not claim universal adapter support, public directory
approval, verified OS sandbox containment, or a broader production-promotion
platform matrix pass.

## Grok Build Host-Local Live Evidence

Grok Build is verified only for the tested local host range:

- Host: Grok Build 0.2.117.
- Source revision:
  `fbee9cca9b68ace522089cc0de9c77df0d0c356b`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/grok-build-live-verified.md`.
- Positive ACP probe fixture:
  `conformance/adapters/grok-build/grok-acp-probe-positive-fixture.json`.
- Live preflight:
  `work/release-1-17/evidence/preflight/grok-build-preflight-report.json`.
- Bounded containment receipt:
  `work/release-1-17/evidence/grok-build-containment-receipt.json`.
- Live host conformance receipt:
  `work/release-1-17/evidence/live-host-receipts/grok-build.json`.
- Live host conformance validation:
  `work/release-1-17/evidence/live-host-conformance-grok-build.json`.
- Live calibration receipt:
  `work/release-1-17/evidence/live-calibration-receipts/grok-build.json`.
- Live calibration validation:
  `work/release-1-17/evidence/live-calibration-verification-grok-build.json`.
- ALK lifecycle final proof:
  `work/release-1-17/evidence/grok-build/full-lifecycle/final/final-proof-r2.json`.

This evidence does not claim universal adapter support, public directory
approval, verified OS sandbox containment, or a broader production-promotion
platform matrix pass.

## OpenInterpreter Host-Local Live Evidence

OpenInterpreter is verified only for the tested local host range:

- Host: `interpreter` 0.0.34.
- Source revision:
  `52cfa2fd5a97823155c552cb9ae27b735fc85713`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/openinterpreter-live-verified.md`.
- Live preflight:
  `work/release-1-18/evidence/preflight/openinterpreter-preflight-report-live-ready.json`.
- Bounded containment receipt:
  `work/release-1-18/evidence/openinterpreter-containment-receipt-live-ready.json`.
- Live host conformance receipt:
  `work/release-1-18/evidence/live-host-receipts/openinterpreter.json`.
- Live host conformance validation:
  `work/release-1-18/evidence/live-host-conformance-openinterpreter.json`.
- Live calibration receipt:
  `work/release-1-18/evidence/live-calibration-receipts/openinterpreter.json`.
- Live calibration validation:
  `work/release-1-18/evidence/live-calibration-verification-openinterpreter.json`.
- ALK lifecycle final proof:
  `work/release-1-18/evidence/openinterpreter/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, verified OS sandbox containment, or a broader production-promotion
platform matrix pass. The containment evidence is limited to the bounded
ephemeral read-only harness invocation policy.

## Pi Live Evidence

Pi is verified only for the tested local host range:

- Host: Pi 0.83.0.
- Source revision:
  `75317878358a3dffa4b503cdb8bd8fff40de770b`.
- Committed redacted evidence summary:
  `docs/adapters/evidence/pi-live-verified.md`.
- Install/source probe:
  `work/release-1-19/evidence/pi-install-probe.json`.
- Live preflight:
  `work/release-1-19/evidence/preflight/pi-preflight-report-live-ready.json`.
- Bounded containment receipt:
  `work/release-1-19/evidence/pi-containment-receipt-live-ready.json`.
- Live host conformance receipt:
  `work/release-1-19/evidence/live-host-receipts/pi.json`.
- Live host conformance validation:
  `work/release-1-19/evidence/live-host-conformance-pi.json`.
- Live calibration receipt:
  `work/release-1-19/evidence/live-calibration-receipts/pi.json`.
- Live calibration validation:
  `work/release-1-19/evidence/live-calibration-verification-pi.json`.
- Host env hygiene:
  `work/release-1-19/evidence/host-env-hygiene-pi-harness-reports.json`.
- Host env hygiene scanned evidence:
  `work/release-1-19/evidence/host-env-hygiene-pi-all-scanned.json`.
- ALK lifecycle final proof:
  `work/release-1-19/evidence/pi/full-lifecycle/final/final-proof.json`.

This evidence does not claim universal adapter support, public directory
approval, ACP support, verified OS sandbox containment, or a broader
production-promotion platform matrix pass. The containment evidence is limited
to the bounded no-tools/no-session/no project-context harness invocation
policy.

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
