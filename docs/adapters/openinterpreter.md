# OpenInterpreter Adapter

OpenInterpreter is represented as an `EXPERIMENTAL` secondary adapter with a
host-local compatible CLI projection. ALK owns the portable lifecycle envelopes;
the adapter owns host-specific launch, wait, cancel, event and usage mapping.

Tracked source artifacts:

- `adapters/openinterpreter/adapter.descriptor.json`
- `adapters/openinterpreter/capabilities.manifest.json`
- `conformance/adapters/openinterpreter/offline-baseline.json`

The source tree contains deterministic offline conformance only. No live host
range, production promotion or public package claim is made.
