# Pi live evidence

Status: `VERIFIED` for Pi 0.83.0 on the tested host-local provider/model
binding.

Scope:

- Host: Pi 0.83.0.
- Provider/model binding: host-local, redacted in committed docs.
- Adapter descriptor: `adapters/pi/adapter.descriptor.json`.
- Capability manifest: `adapters/pi/capabilities.manifest.json`.
- Source revision used for live receipts:
  `75317878358a3dffa4b503cdb8bd8fff40de770b`.
- Production promotion claimed: false.
- Public package or directory approval claimed: false.

Accepted evidence:

- Install/source probe: `PASS`.
  `work/release-1-19/evidence/pi-install-probe.json`
  (`sha256:77b4d4744777aa29df2e208851ed68d96e473036a96a5a5daff561503bd17791`).
- Preflight: `PASS`.
  `work/release-1-19/evidence/preflight/pi-preflight-report-live-ready.json`
  (`sha256:c2b220fc798916b699baff201ff56f1034c56e0de36a8f26a6701355d61e5820`).
- Bounded containment receipt: `PASS`.
  `work/release-1-19/evidence/pi-containment-receipt-live-ready.json`
  (`sha256:cfd61eb9b91b003c0f5453841941629d57f9d3bc395c75649e10dca79c0b83c8`).
- Live host conformance: `PASS`, 14/14 baseline operations.
  `work/release-1-19/evidence/live-host-conformance-pi.json`
  (`sha256:9fbc54417e89b973e48e0343c6bdf76de1fd9ce13f8fa179067c13c20a107eb7`).
- Live host receipt:
  `work/release-1-19/evidence/live-host-receipts/pi.json`
  (`sha256:318c5731c8e16c2ca59bca147432a989392a3660adc9bcd24aa43d0646168c7e`).
- Live calibration: `PASS`, 14/14 scenario/cohort runs,
  `qualityRegressionCount=0`.
  `work/release-1-19/evidence/live-calibration-verification-pi.json`
  (`sha256:a044ff796d79ed4efcb625261fd900126a90c21b312b5b0550d05de9d9d5df26`).
- Live calibration receipt:
  `work/release-1-19/evidence/live-calibration-receipts/pi.json`
  (`sha256:dc434c31ac791ff7ccbecfb34954e23135ad97f250340898d2372ace134cac8c`).
- Host env hygiene, harness reports: `PASS`.
  `work/release-1-19/evidence/host-env-hygiene-pi-harness-reports.json`
  (`sha256:93b72385e260b95b272db8ecd4c9434b12e9f0956e0167ecf3d6be6a244eb666`).
- Host env hygiene, scanned evidence: `PASS`.
  `work/release-1-19/evidence/host-env-hygiene-pi-all-scanned.json`
  (`sha256:f98f64dcca61b8841d44efc6c3821b71917d3460a65a6ba39ebba59fea60e87e`).
- ALK lifecycle final proof:
  `work/release-1-19/evidence/pi/full-lifecycle/final/final-proof.json`
  (`sha256:581ad5a82e5525e7bdc1bd7f7b48d301588d25497731fc4cc80e5dd70866a330`).

Resource accounting:

- Live conformance budget usage: 14 invocations, 6996 billable tokens,
  58.558 wall seconds.
- Live calibration budget usage: 14 invocations, 6708 billable tokens,
  45.372 wall seconds.
- Workflow final proof: `READY_FOR_FINALIZATION`, 4/4 workflow tasks accepted,
  final proof hash
  `581ad5a82e5525e7bdc1bd7f7b48d301588d25497731fc4cc80e5dd70866a330`.
- Budget mode: `subscription`; USD-cost accounting is host-reported and is not
  required for this non-metered promotion gate.

Decision:

Pi is promoted from `EXPERIMENTAL` to host-specific `VERIFIED` for Pi 0.83.0
in this source tree. The decision is limited to the tested host range and
committed evidence summary above. It does not claim public package approval,
public directory approval, production platform promotion, ACP support, or
sandbox containment beyond the bounded no-tools/no-session/no-context harness
policy.
