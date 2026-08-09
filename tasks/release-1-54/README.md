# Release 1.54.0 Host-local token accounting

Status: `FROZEN` after independent OpenCode ownership re-audit.

## Goal

Move exact token normalization to host-local adapter code while keeping the
portable core's fallback calculation conservative, explicitly estimated and
unable to satisfy S1/S2 usage gates.

## Scope

- Define an adapter-local normalizer contract that emits the existing canonical
  model usage receipt as a sidecar to the existing host-operation receipt.
- Convert Gemini CLI, Kimi Code and Qwen Code bounded runners into reference
  normalizer implementations.
- Move their existing stream parsing behind the adapter-local normalizers so
  runners and live harnesses reuse one parser instead of keeping parallel
  host-format implementations.
- Validate each descriptor's normalizer declaration and keep fixture-only
  support distinct from qualified live attestation.
- Bind normalizer output to operation, route, adapter, host, model hash and a
  path-free source artifact identity.
- Make the core distinguish host-attested, estimated, missing and invalid usage.
- Keep adapters without a proven host usage export visibly unproven.
- Update the exact package version in every user-visible package-install
  surface enforced by the documentation gate.

## Non-goals

- No provider API calls or provider SDK in ALK core.
- No claim that every adapter can report exact token counts.
- No new competing model-usage receipt schema.
- No change to the existing host-operation receipt schema; its `usage` object
  remains operation telemetry, while only the canonical model-usage sidecar can
  authorize S1/S2 acceptance.

## Dependency

This package depends on `release-1-53`.

## Guarantee

Exact counts are accepted only when an adapter normalizer can bind them to
host-produced evidence. Otherwise ALK emits a conservative estimate or blocks
the S1/S2 acceptance gate according to the derived risk profile.
