# Acceptance criteria

| ID | Requirement IDs | Evidence IDs | Statement |
| --- | --- | --- | --- |
| `AC64-REUSE-CONTRACT` | `R64-01` | `EV64-REUSE-CONTRACT` | Host-local normalizers emit and validate the existing canonical model usage receipt as a sidecar bound to operation, route, adapter/host, model hash and path-free source artifact identity; no competing usage or host-operation schema is introduced. |
| `AC64-CORE-FALLBACK` | `R64-02` | `EV64-CORE-FALLBACK` | Core aggregation labels conservative estimates, missing usage and host attestation distinctly, requires both `source: host` and `status: ATTESTED`, and never upgrades an estimate to attested evidence. |
| `AC64-REFERENCE-ADAPTERS` | `R64-03` | `EV64-REFERENCE-ADAPTERS` | Gemini CLI, Kimi Code and Qwen Code normalizers parse bounded fixture evidence and preserve host source identity, redaction and receipt binding. |
| `AC64-UNPROVEN-BOUNDARY` | `R64-04` | `EV64-UNPROVEN-BOUNDARY` | Adapters without a qualified usage export remain unproven and their output cannot satisfy S1/S2 usage gates. |
| `AC64-SECURITY` | `R64-05` | `EV64-SECURITY` | Normalizers enforce bounded reads, extract only allowlisted fields, emit no raw text, secret-like value or local path, and contain no provider SDK, network, process-launch or dynamic-import path. |
| `AC64-DOCS` | `R64-06` | `EV64-DOCS` | English and Russian documentation explains attested versus estimated counters and per-adapter support honestly. |
| `AC64-RELEASE-METADATA` | `R64-07` | `EV64-RELEASE-METADATA` | Version, plugin, marketplace and user-visible exact package-pin surfaces are updated to `1.54.0` / `v1.54.0` and pass publication validation. |
| `AC64-SINGLE-PARSER` | `R64-08` | `EV64-SINGLE-PARSER` | Each reference adapter runner and live harness loads one adapter-local host-format parser through a contained shared loader, while descriptor validation enforces the specified `usageNormalization` contract and rejects unsafe or falsely qualified declarations. |
