# Adapter scaffold templates

`agent-lifecycle adapter scaffold` creates a minimal host projection skeleton:

- `adapters/<host>/adapter.descriptor.json`
- `conformance/adapters/<host>/offline-baseline.json`
- `docs/adapters/<host>.md`

The scaffold is intentionally limited to `EXPERIMENTAL` metadata. It does not
generate lifecycle semantics, concrete provider model names, live evidence, or
`VERIFIED` maturity claims.
