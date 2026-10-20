# Security policy

Agent Lifecycle Kit maintains a deterministic core API/CLI with the package
classifier Production/Stable. This is a bounded core maintenance claim, not a
certification of every deployment, host or model integration. Treat native host
adapters as experimental unless the release support matrix marks a route as
`VERIFIED`; its documented limitations still apply.

## Reporting

Report security issues privately to the repository maintainers. Do not publish
working exploit details until a fix or mitigation is available.

## Release claims

Offline tests, deterministic packaging, neutrality scanning and supported-platform
CI provide source-bound evidence only for the checks they actually execute. They
do not claim production promotion. Any stronger production-promotion contract
requires its external signed platform, neutrality and live-cost evidence; local
tests, schema validity and prepared packets cannot replace it. Missing telemetry
is UNAVAILABLE/null, never zero.

Distinguish designed requirements, locally enforced validation, caller-declared
data and externally attested claims. See
[the SDLC boundary](docs/architecture/sdlc-boundary.md) and the per-route support
matrix. An editable same-account plugin is not an external trusted operator.

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

Host-local state, lifecycle plans/evidence and generated release output are not
source authority. Repository hygiene rejects their explicit roots from the
current index and rejects host-local/lifecycle roots from reachable candidate
and publication history. Similarly named product roots such as
`.claude-plugin/` remain allowed. Published history is rewritten only for
confirmed secrets or prohibited host-local content, never merely to remove
stale non-secret release notes.
