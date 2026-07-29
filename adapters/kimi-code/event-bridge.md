# Kimi Code event bridge

This is an EXPERIMENTAL bounded event bridge. The source runner normalizes
Kimi Code `stream-json` output into `agent-host-operation-receipt.v1` records
for live-harness validation.

Runtime dispatch remains fail-closed for unsupported operations. Host-specific
`VERIFIED` support still requires accepted live host conformance, calibration,
and lifecycle final proof evidence.
