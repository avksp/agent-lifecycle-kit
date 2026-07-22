# Release security

Offline release-candidate generation must be deterministic and local. It may
write release inventory and evidence files, but it must not read credentials or
require network access.

Production promotion must use external signing and verification authorities.
Those authorities are not stored in this repository.

Security-sensitive release rules:

- no mutable release alias is an identity;
- no production or verified adapter claim without matching evidence;
- no private key, token, cookie or credential in release artifacts;
- no source-project path or local-machine path in release artifacts;
- no host-specific lifecycle semantics in the shared core.
