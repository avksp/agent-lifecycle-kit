# Qwen Code GLM 5.2 live evidence

Status: `VERIFIED` for Qwen Code `0.21.0` on the tested local GLM 5.2 binding.

Scope:

- Host: Qwen Code `0.21.0`.
- Adapter descriptor: `adapters/qwen-code/adapter.descriptor.json`.
- Capability manifest: `adapters/qwen-code/capabilities.manifest.json`.
- Source revision: `6c6b40210ee28de4b6a5993367af89e629fb99ff`.
- Production promotion claimed: false.
- Public package or directory approval claimed: false.

Accepted evidence:

- Preflight: `PASS`.
  `tasks/release-0-11/evidence/qwen-code/live-preflight/qwen-code-preflight-report.json`
  (`sha256:c08dad562daf65f908510bbb035fa589d4bdc19d8b4d9e5384029c203d3a3f82`).
- Live host conformance: `PASS`, 13/13 baseline operations.
  `tasks/release-0-11/evidence/qwen-code/live-host-conformance-qwen-code.json`
  (`sha256:f74ae247b79a8f689a97f1fdfa045af52eafc3072c17d884e634d2ee4d267ec0`).
- Live host receipt:
  `tasks/release-0-11/evidence/qwen-code/live-host-receipts/qwen-code.json`
  (`sha256:7b719a03ce1daac56e120bbdea312b8dc25c23b95c7a2fba33781aa9ec1fc8d1`).
- Live calibration: `PASS`, 14/14 scenario/cohort runs,
  `qualityRegressionCount=0`.
  `tasks/release-0-11/evidence/qwen-code/live-calibration-verification-qwen-code.json`
  (`sha256:96d10f9d39d17287a34bdc345e6715f98cab7ebc25809e460abdda6dcb6fb236`).
- Live calibration receipt:
  `tasks/release-0-11/evidence/qwen-code/live-calibration-receipts/qwen-code.json`
  (`sha256:0bcc375ceafad1e5ce4ed5d3dab076101f8a26d6c6038f8c19603c10b15d37d8`).
- ALK lifecycle final proof:
  `tasks/release-0-11/evidence/qwen-code/full-lifecycle/final/final-proof.json`
  (`sha256:5576e94553b8bf7f50a865db73f4ac8cd50f31a5f5ed16e5f309227768e3cee8`).

Resource accounting:

- Live conformance budget usage: 13 invocations, 190255 billable tokens,
  101.186 wall seconds.
- Live calibration budget usage: 14 invocations, 189148 billable tokens,
  78.302 wall seconds.
- Workflow aggregate usage receipt: 379403 billable tokens, 378149 input
  tokens, 1254 output tokens, 45625 cumulative context bytes, 0 tool calls,
  183 rounded wall seconds.

Decision:

Qwen Code is promoted from `EXPERIMENTAL` to host-specific `VERIFIED` for
Qwen Code `0.21.0` in this source tree. This decision is limited to the tested
host range and the committed evidence above. It does not claim public package
approval, public directory approval, universal adapter support, or broader
production-promotion platform readiness.
