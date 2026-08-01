# Grok Build live evidence

Status: `VERIFIED` for Grok Build `0.2.117` on the tested host-local
provider/model binding.

Scope:

- Host: Grok Build `0.2.117`.
- Provider/model binding: host-local, redacted in committed docs.
- Adapter descriptor: `adapters/grok-build/adapter.descriptor.json`.
- Capability manifest: `adapters/grok-build/capabilities.manifest.json`.
- Source revision used for live receipts:
  `fbee9cca9b68ace522089cc0de9c77df0d0c356b`.
- Production promotion claimed: false.
- Public package or directory approval claimed: false.

Accepted evidence:

- Preflight: `PASS`.
  `work/release-1-17/evidence/preflight/grok-build-preflight-report.json`
  (`sha256:6b03af03ef90a322089fa6993e1bf463069019dc367c4e77ca23d6cd4307779c`).
- Bounded containment receipt: `PASS`.
  `work/release-1-17/evidence/grok-build-containment-receipt.json`
  (`sha256:e636fa079ef448c4c4cff8281a87b2a4d63a9de0297dcbc30b73092d8169292a`).
- Positive ACP probe fixture: `PASS`.
  `conformance/adapters/grok-build/grok-acp-probe-positive-fixture.json`
  (`sha256:e03dee549955db11aa09803ca2186913c60fa6566d6702d5f9278a1fbe62b20d`).
- Live host conformance: `PASS`, 14/14 baseline operations.
  `work/release-1-17/evidence/live-host-conformance-grok-build.json`
  (`sha256:b8b813b455036870bd800b5a379c7029685e11d6c6cff27389daf5a8881bc056`).
- Live host receipt:
  `work/release-1-17/evidence/live-host-receipts/grok-build.json`
  (`sha256:8611a8b4be46d59ad43040c63e626cd282c50eec26ad77bce060567af6fc39b7`).
- Live calibration: `PASS`, 14/14 scenario/cohort runs,
  `qualityRegressionCount=0`.
  `work/release-1-17/evidence/live-calibration-verification-grok-build.json`
  (`sha256:769c4e8f473cbe63fcb9655af7dec1f4734fee362e70c485727ee0d46135ce5e`).
- Live calibration receipt:
  `work/release-1-17/evidence/live-calibration-receipts/grok-build.json`
  (`sha256:466d0f034e9670cbe6d37ff1fddc0a05a66389d7d4fb223490bfa51abcf11bed`).
- ALK lifecycle final proof:
  `work/release-1-17/evidence/grok-build/full-lifecycle/final/final-proof-r2.json`
  (`sha256:f528a9f4849c8194384a1fa4c9a947dd2657dfabc6a6dcd83af560a0fd62bc09`).

Resource accounting:

- Live conformance budget usage: 14 invocations, 166733 billable tokens,
  84.977 wall seconds.
- Live calibration budget usage: 14 invocations, 166176 billable tokens,
  89.633 wall seconds.
- Workflow aggregate usage receipt: 332909 billable tokens,
  174.61 wall seconds.
- Budget mode: `subscription`; USD-cost accounting is host-reported and is not
  required for this non-metered promotion gate.

Decision:

Grok Build is promoted from `EXPERIMENTAL` to host-specific `VERIFIED` for Grok
Build `0.2.117` in this source tree. The decision is limited to the tested host
range and committed evidence summary above. It does not claim public package
approval, public directory approval, universal ACP support, production platform
promotion, or sandbox containment beyond the bounded plan-mode harness policy.
