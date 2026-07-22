# Security Policy

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

## Secret handling

Secrets, private signing keys, local credentials, provider tokens and host
session cookies must never be committed, written into lifecycle evidence, or
copied into task packets.
