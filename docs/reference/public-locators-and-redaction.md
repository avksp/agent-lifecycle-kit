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

Standalone token recognition includes GitLab `glpat-`, npm `npm_`, Stripe
secret/restricted `sk_live_`, `sk_test_`, `rk_live_`, `rk_test_`, Hugging Face
`hf_` and Google `AIza` forms. The shared recognizer also applies inside URL
components, including bounded percent-encoding layers, and to adapter process
output. Stripe publishable `pk_live_` and `pk_test_` values remain public.

Signed URL query and fragment parameters remove `sig`, `signature`, AWS
`X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-Security-Token`, Google
`X-Goog-Signature`, `X-Goog-Credential`, `AWSAccessKeyId` and `GoogleAccessId`
values. Names are case insensitive and encoded names are inspected with a
bounded decoder. Ordinary URL paths and unrelated parameters remain visible.
This query rule does not remove public `signature` fields from structured
verification receipts. All consumers retain the same shared policy and
redaction flags; there is no separate adapter-specific token recognizer.

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
