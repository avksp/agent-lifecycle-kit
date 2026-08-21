# Security policy

Agent Lifecycle Kit is pre-release software. Treat all native host adapters as
experimental unless the release support matrix marks a host as `VERIFIED`.

## Reporting

Report security issues privately to the repository maintainers. Do not publish
working exploit details until a fix or mitigation is available.

## Release claims

The offline release candidate proves only local deterministic packaging,
neutrality scanning and contract validation. It does not claim production
promotion. Production promotion requires external signed receipts for platform
matrix execution, release neutrality and live cost calibration.

## Release 1.75 security boundary

Release 1.75 strengthens the proof and publication boundary while keeping the
core provider-neutral and offline:

- neutrality receipts bind the signed claims to the operation and primary
  artifact;
- Git revision inputs are validated before read-only reports are produced;
- repository evidence rejects symlinked inputs and local launch evidence binds
  the resolved executable identity;
- shared redaction covers common standalone token formats before evidence is
  persisted;
- bounded JSON handling, private artifact permissions and strict Ed25519
  decoding fail closed;
- the frozen plan package is bound by its lock and verified before audit or
  execution;
- CI and publication use protected release references, pinned Actions and
  PyPI Trusted Publishing.

The release does not add a host broker, a model client or implicit trust in a
local launch profile.

## Secret handling

Secrets, private signing keys, local credentials, provider tokens and host
session cookies must never be committed, written into lifecycle evidence, or
copied into task packets.
