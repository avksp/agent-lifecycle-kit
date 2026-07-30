# OpenCode GLM 5.2 live evidence

Status: host-specific `VERIFIED` for OpenCode CLI `1.18.9`.

Scope:

- Host: OpenCode CLI `1.18.9`.
- Tested at: `2026-07-29`.
- Source revision: `6c6b40210ee28de4b6a5993367af89e629fb99ff`.
- Maturity claim: `VERIFIED` for this host range only.
- Production promotion: not claimed.
- npm publication or public directory approval: not claimed.

Accepted evidence:

| Gate | Status | Evidence |
| --- | --- | --- |
| Live preflight | `PASS` | `work/release-0-7/evidence/opencode/preflight/opencode-glm52-preflight-report.json` |
| Live host conformance | `PASS` | `work/release-0-7/evidence/opencode/live-host-conformance-opencode.json` |
| Live host receipt | `PASS` | `work/release-0-7/evidence/opencode/live-host-receipts/opencode.json`, receipt hash `058a0124263c5ec53d5a27c9ca0127dddd1e4cef7d9dda3f45bb4c27747b94fa` |
| Live calibration | `PASS` | `work/release-0-7/evidence/opencode/live-calibration-verification-opencode.json` |
| Live calibration receipt | `PASS` | `work/release-0-7/evidence/opencode/live-calibration-receipts/opencode.json`, receipt hash `03e1f52c7a996da89e02b822f82fc719948c741ce55196bf7b660346bc651df4` |
| Full ALK lifecycle | `PASS` | `task-start` -> `task-result` -> `task-accept` -> `finalize`, final proof hash `5ee9f2f928367ad9ef6e46aba27797122f65d7569c5401063305059609b15d6e` |

Usage summary from the accepted lifecycle proof:

- billable tokens: `210028`;
- input tokens: `20256`;
- output tokens: `728`;
- wall seconds: `246`;
- usage attestation: host-attested through normalized live receipts.

This evidence does not claim compatibility with untested OpenCode versions,
global adapter support, production promotion, or publication.
