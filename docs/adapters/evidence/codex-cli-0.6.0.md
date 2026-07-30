# Codex CLI 0.6.0 Evidence Summary

This is the committed, redacted summary for the Codex host-specific `VERIFIED`
claim. Raw receipts and diagnostics remain local release evidence under
`work/release-0-6/evidence/` because that tree is intentionally ignored.

## Claim

- Adapter: `codex`.
- Host: Codex CLI 0.145.0.
- Tested host version: Codex CLI 0.145.0.
- Source revision:
  `b01a1793e42f52e20077a7aa26b8e4e25c3bd216`.
- Maturity claim: `VERIFIED` for this host range only.
- Budget mode: `subscription` with invocation, token, and wall-clock caps.
- Production promotion claimed: false.
- Public directory approval claimed: false.
- Universal adapter support claimed: false.

## Gate Results

| Gate | Result | Key metrics |
| --- | --- | --- |
| Preflight | `PASS` | CLI version/help, clean worktree, 13-operation budget gate |
| Fixture envelope check | `PASS` | 13 synthetic host-operation envelopes |
| Canary | `PASS` | 1 invocation, 16326 billable tokens |
| Live host conformance | `PASS` | 13 operations, 232285 billable tokens, 158.575 seconds |
| Live calibration | `PASS` | 14 invocations, 229558 billable tokens, 126.324 seconds |
| Full ALK lifecycle | `PASS` | `task-start` -> `task-result` -> `task-accept` -> `finalize`, final proof hash `0258063d29c09444c08ee555bea53bd8fa14899bd95598daddc992b4877a6c3c` |

## Local Raw Evidence

- `work/release-0-6/evidence/codex-live-promotion/preflight/codex-preflight-report.json`
- `work/release-0-6/evidence/codex-live-promotion/preflight/codex-fixture-check-report.json`
- `work/release-0-6/evidence/codex-live-promotion/preflight/codex-canary.jsonl`
- `work/release-0-6/evidence/codex-live-promotion/live-host-receipts/codex.json`
- `work/release-0-6/evidence/codex-live-promotion/live-host-conformance-codex.json`
- `work/release-0-6/evidence/codex-live-promotion/live-calibration-receipts/codex.json`
- `work/release-0-6/evidence/codex-live-promotion/live-calibration-verification-codex.json`
- `work/release-0-6/evidence/codex-live-promotion/full-lifecycle/final/final-proof.json`

Raw Codex JSONL transcripts are not committed. The retained local diagnostics
store hashes, byte counts, return codes, and redacted summaries.
