# Claude Code 0.5.0 evidence summary

This is the committed, redacted summary for the Claude Code host-specific
`VERIFIED` claim. Raw receipts and diagnostics remain local release evidence
under `work/release-0-5/evidence/` because that tree is intentionally ignored.

## Claim

- Adapter: `claude`.
- Host: `claude-code`.
- Tested host version: Claude Code 2.1.220.
- Source revision:
  `6bb3b58ee01d028fe21cef209c284efc79e55ceb`.
- Support-level claim: `VERIFIED` for this host range only.
- Production promotion claimed: false.
- Public directory approval claimed: false.
- Universal adapter support claimed: false.

## Gate results

| Gate | Result | Key metrics |
| --- | --- | --- |
| Patch plan validation | `PASS` | 19 structural checks |
| Preflight | `PASS` | CLI version/help/print-help, clean worktree, budget gate |
| Canary | `PASS` | 1 invocation, 26895 billable tokens, 0.0715996 USD |
| Live host conformance | `PASS` | 13 operations, 481927 billable tokens, 316.586 seconds |
| Live calibration | `PASS` | 14 invocations, 242738 billable tokens, 230.989 seconds |
| Full ALK lifecycle | `PASS` | `task-start` -> `task-result` -> `task-accept` -> `finalize`, final proof hash `58f0b77c48fee53b0c246e58baf244551f06b4b2322432959b79bbf8bf899ede` |

## Local raw evidence

- `work/release-0-5/evidence/0.5.1-claude-live-promotion/live-host-promotion-plan-validation.json`
- `work/release-0-5/evidence/0.5.1-claude-live-promotion/preflight/claude-code-preflight-report.json`
- `work/release-0-5/evidence/0.5.1-claude-live-promotion/canary/claude-code-canary-summary.json`
- `work/release-0-5/evidence/live-host-receipts/claude-code.json`
- `work/release-0-5/evidence/live-host-conformance-claude-code.json`
- `work/release-0-5/evidence/live-calibration/claude-code.json`
- `work/release-0-5/evidence/live-calibration-verification-claude-code.json`
- `work/release-0-5/evidence/0.5.1-claude-live-promotion/full-lifecycle/final/final-proof.json`
- `work/release-0-5/evidence/live-promotion-audit-claude-code.json`

Raw Claude stream-json transcripts were not committed because host init
metadata includes machine-local absolute paths. The retained local diagnostics
store hashes, byte counts, return codes, and redacted summaries.
