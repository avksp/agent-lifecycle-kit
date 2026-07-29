# Hermes GLM 5.2 live evidence

Status: host-specific `VERIFIED` for Hermes Agent `v0.19.0`.

Scope:

- Host: Hermes Agent `v0.19.0`.
- Host source revision: `d71033a4`.
- Tested at: `2026-07-29`.
- Maturity claim: `VERIFIED` for this host range only.
- Production promotion: not claimed.
- Public directory approval or publication: not claimed.

Accepted evidence:

| Gate | Status | Evidence |
| --- | --- | --- |
| Live preflight | `PASS` | `tasks/release-0-8/evidence/hermes/preflight/hermes-glm52-preflight-report.json` |
| Live host conformance | `PASS` | `tasks/release-0-8/evidence/hermes/live-host-conformance-hermes.json` |
| Live host receipt | `PASS` | `tasks/release-0-8/evidence/hermes/live-host-receipts/hermes.json`, receipt hash `090d0163fe4911f8b9c80679fc8fce3df6e3c0f934a7bf19cfe0029c32b4b7f8` |
| Live calibration | `PASS` | `tasks/release-0-8/evidence/hermes/live-calibration-verification-hermes.json` |
| Live calibration receipt | `PASS` | `tasks/release-0-8/evidence/hermes/live-calibration-receipts/hermes.json`, receipt hash `c53d92045c27c9fe5881ee5212494ff407f76daeb82c7f47c7d52dc5ae9b5ba8` |
| Full ALK lifecycle | `PASS` | `task-start` -> `task-result` -> `task-accept` -> `finalize`, final proof hash `8b3de2f2e688811ebc8bf0c7f2e7a853a90d122401d322c30a706acd127050d3` |

Usage summary from the accepted lifecycle proof:

- billable tokens: `1712264`;
- input tokens: `136948`;
- output tokens: `19220`;
- wall seconds: `853`;
- usage attestation: host-attested through normalized live receipts.

This evidence does not claim compatibility with untested Hermes versions,
global adapter support, production promotion, or publication.
