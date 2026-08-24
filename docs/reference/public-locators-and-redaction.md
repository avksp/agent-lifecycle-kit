# Public locators and redaction

ALK can retain a public evidence locator when it is an ordinary HTTP(S) URL.
This contract is local and deterministic: ALK does not fetch the URL, resolve
it, or grant the URL any filesystem, host or network authority.

## Accepted form

The shared contract is `agent-public-evidence-locator.v1`. It accepts `http`
and `https` only, limits the UTF-8 value to 4096 bytes, lowercases the scheme
and hostname, removes the default port, and canonicalizes IPv6 and IDN hosts.
The path, query and fragment remain part of the evidence locator.

For example:

```text
HTTPS://EXAMPLE.COM:443/reports/1#Summary
https://example.com/reports/1#Summary
```

The second line is the canonical value of the first. Canonicalization is not a
network request and does not prove that the resource exists.

## Rejected or redacted values

The contract rejects empty values, unsupported schemes such as `file:`,
`data:` and `javascript:`, credentials in the authority, invalid hosts or
ports, control characters and values over the byte limit. Research evidence
with `kind: "url"` must already contain the canonical HTTP(S) value; a
non-canonical or unsafe value fails closed with a stable blocker code.

Shared receipt redaction continues to remove credentials, sensitive query or
fragment values, bearer tokens, known token formats and local absolute paths.
The URL path itself is not mistaken for a local path. A redacted receipt keeps
its `redaction` or `redactionStatus` outcome, and no raw secret or local path is
stored.

## Surface coverage

The same primitive is consumed by research evidence, external-context
citations, adapter process output, Review Mesh results, host-operation
receipts, context events and both context-checkpoint builders and stores.
Every consumer remains offline and provider-neutral. The contract changes data
normalization only; it does not turn evidence into authority, proof or an
implementation permission.

## Security boundary

Do not use a public locator as a command, import path, host executable, proxy
configuration or approval source. If a source needs to be opened, fetching it
belongs to an explicitly authorized external tool and its result must return
through the normal evidence and review contracts.
