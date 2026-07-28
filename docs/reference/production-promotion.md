# Production promotion contract

Production promotion is outside the offline source-release proof.

Required external evidence:

- signed CI matrix aggregate for Ubuntu, macOS and Windows on CPython 3.11,
  3.12 and 3.13;
- signed release neutrality receipt over the promoted release generation and
  the required repository object scope;
- signed live host lifecycle conformance receipt per promoted host;
- signed live cost calibration profile and receipt;
- independent final audit confirming that the release does not claim support
  beyond its evidence.

If any authority, receipt, signature, source binding, platform leg or live
host conformance or live calibration input is missing, promotion is blocked.

Live host lifecycle conformance must be validated before promotion:

```bash
python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts codex,claude-code \
  --evidence <live-host-conformance-evidence.json>
```

Live cost calibration must also be validated before promotion:

```bash
python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt-dir <live-calibration-receipts-dir> \
  --promoted-hosts codex,claude-code \
  --evidence <live-calibration-evidence.json>
```

Each receipt covers one host. A universal `VERIFIED` promotion must include one
passing receipt for every host listed in the calibration profile. Each host
receipt must cover every required scenario/cohort, including the
`S1-SMALL-CONTEXT-4K-STRICT-01` compact-context scenario. Synthetic replay
receipts, missing usage attestations, host-operation envelope bypasses and
quality regressions are blocking.
