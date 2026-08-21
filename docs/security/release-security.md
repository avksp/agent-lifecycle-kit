# Release security

Offline source-release generation must be deterministic and local. It may write
release inventory and evidence files, but it must not read credentials or
require network access.

## Release 1.75 controls

Release 1.75 provides one connected security proof for the local source and
publication boundaries:

- signed neutrality receipts bind claims, operation and primary artifact;
- Git revision arguments are checked before a read-only report is produced;
- repository evidence rejects symlinked inputs, while local launch evidence
  records the resolved executable identity;
- shared redaction removes common standalone tokens before evidence is stored;
- JSON limits, private file permissions and strict Ed25519 decoding use
  fail-closed checks;
- the frozen plan package is bound to its lock before audit and execution;
- CI and publication use immutable Action references, protected release tags
  and the existing PyPI Trusted Publisher configuration.

The 1.75.0 distribution provenance is verified after the protected release
workflow publishes the wheel and source archive. The earlier 1.74.0 wheel and
source archive already provide a verified Trusted Publishing baseline.

Production promotion must use external signing and verification authorities.
Those authorities are not stored in this repository.

Security-sensitive release rules:

- no mutable release alias is an identity;
- no production or verified adapter claim without matching evidence;
- no private key, token, cookie or credential in release artifacts;
- no source-project path or local-machine path in release artifacts;
- no host-specific lifecycle semantics in the shared core.
- host-local env files used by live harnesses require explicit
  `--host-env-allow` and `validate_host_env_hygiene.py` evidence before the
  related reports can be accepted.

Security and resource checks are separate gates. A run can pass lifecycle cost
accounting and still fail release security if it leaks local paths, secrets or
unsupported adapter claims. A run can pass security and still fail resource
discipline if pipeline compliance cost exceeds the selected mode without a
reason.
