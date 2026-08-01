# OpenInterpreter live evidence

Status: `VERIFIED` for `interpreter` 0.0.34 on the tested host-local
provider/model binding.

Scope:

- Host: `interpreter` 0.0.34.
- Provider/model binding: host-local, redacted in committed docs.
- Adapter descriptor: `adapters/openinterpreter/adapter.descriptor.json`.
- Capability manifest: `adapters/openinterpreter/capabilities.manifest.json`.
- Source revision used for live receipts:
  `52cfa2fd5a97823155c552cb9ae27b735fc85713`.
- Production promotion claimed: false.
- Public package or directory approval claimed: false.

Accepted evidence:

- Preflight: `PASS`.
  `work/release-1-18/evidence/preflight/openinterpreter-preflight-report-live-ready.json`
  (`sha256:a79f8a11389d31ffe76eb682409929f82e90c64720ce66814958dc9ea304bcac`).
- Bounded containment receipt: `PASS`.
  `work/release-1-18/evidence/openinterpreter-containment-receipt-live-ready.json`
  (`sha256:ca6fa30f6f5f50183001f38afb602cec97b80b3da9a147abd0cfbe481ddfa2a5`).
- Live host conformance: `PASS`, 14/14 baseline operations.
  `work/release-1-18/evidence/live-host-conformance-openinterpreter.json`
  (`sha256:30947378201f3a9c09b6c6545011693a273344854391270f6ab6b31948c4d620`).
- Live host receipt:
  `work/release-1-18/evidence/live-host-receipts/openinterpreter.json`
  (`sha256:3b8103665836e0777f946a9c252dbfdb63ca6446cadce8f919d662fb0e7dddc3`).
- Live calibration: `PASS`, 14/14 scenario/cohort runs,
  `qualityRegressionCount=0`.
  `work/release-1-18/evidence/live-calibration-verification-openinterpreter.json`
  (`sha256:29f38e221c0b673206b39da7158fde596ecd08931c34608e34507cdffa070c6e`).
- Live calibration receipt:
  `work/release-1-18/evidence/live-calibration-receipts/openinterpreter.json`
  (`sha256:4d809fe06fc1e49f51e0c47931972a07b742571e1ba3608bb5a3b49be49e2c1d`).
- ALK lifecycle final proof:
  `work/release-1-18/evidence/openinterpreter/full-lifecycle/final/final-proof.json`
  (`sha256:9da564656a0862c6b9c3f8b1ac87a3a17a4801902071bd85cf287040aaa76beb`).

Resource accounting:

- Live conformance budget usage: 14 invocations, 132645 billable tokens,
  99.954 wall seconds.
- Live calibration budget usage: 14 invocations, 132296 billable tokens,
  102.974 wall seconds.
- Workflow final proof: `READY_FOR_FINALIZATION`, 3/3 workflow tasks accepted,
  final proof hash
  `9da564656a0862c6b9c3f8b1ac87a3a17a4801902071bd85cf287040aaa76beb`.
- Budget mode: `subscription`; USD-cost accounting is host-reported and is not
  required for this non-metered promotion gate.

Decision:

OpenInterpreter is promoted from `EXPERIMENTAL` to host-specific `VERIFIED` for
`interpreter` 0.0.34 in this source tree. The decision is limited to the tested
host range and committed evidence summary above. It does not claim public
package approval, public directory approval, production platform promotion, or
sandbox containment beyond the bounded ephemeral read-only harness policy.
