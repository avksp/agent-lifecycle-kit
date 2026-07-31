# Goose live evidence

Status: `VERIFIED` for Goose `1.45.0` on the tested local ZAI GLM 5.2 binding.

Scope:

- Host: Goose `1.45.0`.
- Adapter descriptor: `adapters/goose/adapter.descriptor.json`.
- Capability manifest: `adapters/goose/capabilities.manifest.json`.
- Source revision used for live receipts:
  `87fb1ce58612efbd2121d8eb56f9d54de8fbbcfb`.
- Production promotion claimed: false.
- Public package or directory approval claimed: false.

Accepted evidence:

- Preflight: `PASS`.
  `work/release-1-16/evidence/preflight/goose-preflight-report.json`
  (`sha256:dda78f39e791b7cf3f48f4732f6f9359fe1a9e2bcb7215daf5492f13a160a48f`).
- Bounded containment receipt: `PASS`.
  `work/release-1-16/evidence/goose-containment-receipt.json`
  (`sha256:cc4c63b23211222ec0542f8975a8c44d4a43966c2654587522fc9c24768e3aec`).
- Live host conformance: `PASS`, 14/14 baseline operations.
  `work/release-1-16/evidence/live-host-conformance-goose.json`
  (`sha256:fe741ea76cb6504f64f035237c453622e5565a5217b2c95c58e0010e34f4b537`).
- Live host receipt:
  `work/release-1-16/evidence/live-host-receipts/goose.json`
  (`sha256:ab216edf75ebef82d7d4c9ec23cbb28b8ac334f54fc450bda9ae5da050f850ee`).
- Live calibration: `PASS`, 14/14 scenario/cohort runs,
  `qualityRegressionCount=0`.
  `work/release-1-16/evidence/live-calibration-verification-goose.json`
  (`sha256:0e64b3b74e504c0f5aec7db0f93107928261f17728f9f5fd369f635c59f38529`).
- Live calibration receipt:
  `work/release-1-16/evidence/live-calibration-receipts/goose.json`
  (`sha256:44900cdc9562d5dc5c4fcd938075f4e20d4eb8d6f422d097902583d26a822d17`).
- ALK lifecycle final proof:
  `work/release-1-16/evidence/goose/full-lifecycle/final/final-proof-r5.json`
  (`sha256:b80aedf962849743f203973af370b832f8b203a2625024682dc9fe8f86a6654f`).

Resource accounting:

- Live conformance budget usage: 14 invocations, 5738 billable tokens,
  52.657 wall seconds.
- Live calibration budget usage: 14 invocations, 6371 billable tokens,
  57.052 wall seconds.
- Workflow aggregate usage receipt: 12109 billable tokens, 9546 input tokens,
  2563 output tokens, 26430 cumulative context bytes, 0 tool calls,
  109.709 wall seconds.
- Budget mode: `subscription`; USD-cost accounting is host-reported and is not
  required for this non-metered promotion gate.

Decision:

Goose is promoted from `EXPERIMENTAL` to host-specific `VERIFIED` for Goose
`1.45.0` in this source tree. The decision is limited to the tested host range
and committed evidence summary above. It does not claim public package
approval, public directory approval, universal ACP support, production platform
promotion, or sandbox containment beyond the bounded no-profile harness policy.
