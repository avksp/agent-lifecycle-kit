# Grok Build Adapter

Grok Build is represented as an `EXPERIMENTAL` secondary adapter. Its descriptor
declares an ACP transport only behind a required local probe. The probe receipt
does not start live model calls, and a failed probe leaves the adapter
fail-closed instead of silently falling back to an unverified transport.

Tracked source artifacts:

- `adapters/grok-build/adapter.descriptor.json`
- `adapters/grok-build/capabilities.manifest.json`
- `conformance/adapters/grok-build/offline-baseline.json`
- `conformance/adapters/grok-build/grok-acp-probe-negative-fixture.json`

Promotion to `VERIFIED` requires accepted live host conformance, usage
receipts, resource evidence, sandbox evidence where required, and lifecycle
final proof for the tested host range.
