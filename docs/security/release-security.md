# Release security

Offline source-release generation must be deterministic and local. It may write
release inventory and evidence files, but it must not read credentials or
require network access.

Production promotion must use external signing and verification authorities.
Those authorities are not stored in this repository.

Security-sensitive release rules:

- no mutable release alias is an identity;
- no production or verified adapter claim without matching evidence;
- no private key, token, cookie or credential in release artifacts;
- no source-project path or local-machine path in release artifacts;
- no host-specific lifecycle semantics in the shared core.

Security and resource checks are separate gates. A run can pass lifecycle cost
accounting and still fail release security if it leaks local paths, secrets or
unsupported adapter claims. A run can pass security and still fail resource
discipline if pipeline compliance cost exceeds the selected mode without a
reason.
