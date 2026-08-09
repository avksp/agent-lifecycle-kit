# Host-local token accounting

ALK keeps model and provider telemetry outside the portable core. An adapter
may declare a local usage normalizer that reads one bounded host artifact and
emits the existing `agent-lifecycle-model-usage-receipt.v1` contract. The
descriptor declaration uses `adapter-local-usage-normalizer.v1`.

This separation answers two different questions:

- the adapter normalizer determines which counters the host actually reported;
- the core validates provenance, route binding, budgets and whether those
  counters are acceptable evidence for S1/S2.

## Evidence levels

| Status | Meaning | Accepted for S1/S2 |
| --- | --- | --- |
| `UNSUPPORTED` | No adapter-local normalizer is declared. Core may expose a conservative estimate. | No |
| `FIXTURE_ONLY` | The parser is covered by bounded fixtures, but no live host range has qualified its output. | No |
| `QUALIFIED` | A declared host range and independent qualification evidence cover the normalizer. | Yes, only for `source: host` and `status: ATTESTED` |

Adapter maturity and token-normalizer status are separate. For example, Qwen
Code can remain a `VERIFIED` adapter while its newly factored usage normalizer
is still `FIXTURE_ONLY`. Existing lifecycle evidence is not silently reused as
qualification evidence for a new parser contract.

## Receipt binding

The adapter emits model usage as a sidecar inside a host-operation output. It
does not change `agent-host-operation-receipt.v1`. The sidecar binds:

- operation id and route decision digest;
- adapter id and host;
- provider-neutral model class and a hash of the host-local model binding;
- source artifact SHA-256, byte count and format, without a local path;
- normalizer status and source-file digest.

Raw JSONL, prompts, responses, secrets and local paths are not copied into the
portable receipt. Session ids are retained only when they match the bounded
opaque-id policy.

## Reference adapters

| Adapter | Artifact | Normalizer status |
| --- | --- | --- |
| Gemini CLI | `stream-json` | `FIXTURE_ONLY` |
| Kimi Code | `stream-json` | `FIXTURE_ONLY` |
| Qwen Code | `stream-json` | `FIXTURE_ONLY` |
| Other bundled adapters | Not declared by this contract | `UNSUPPORTED` |

All three reference parsers are loaded from
`adapters/<adapter>/usage_normalizer.py`. The adapter runner and live harness
use that same file through a contained loader. The loader rejects traversal,
symlinks and descriptor/path mismatches.

Validate declarations and parser boundaries:

```bash
python tools/release/validate_host_usage_normalizers.py \
  --adapter-root adapters \
  --evidence work/validation/host-usage-normalizers.json

agent-lifecycle adapter validate \
  --descriptor adapters/qwen-code/adapter.descriptor.json
```

Validate a qualified model-usage receipt against its route and budget:

```bash
agent-lifecycle model usage-check \
  --receipt work/run/model-usage.json \
  --route-decision work/run/model-route.json \
  --budget-targets conformance/core/budget-targets.v1.json
```

Fixture output is exact for that fixture, but it is still `ESTIMATED` evidence
for lifecycle gates. A status label cannot promote it to host attestation.

## Conservative fallback

When exact host evidence is unavailable, core fallback uses a visible
one-token-per-source-byte upper bound. This is deliberately conservative and is
labelled `source: core-estimate`, `status: ESTIMATED`. Aggregation classifies
usage as attested only when both `source: host` and `status: ATTESTED` are
present.

Token accounting remains resource accounting, not price accounting. A host may
report monetary metadata, but ALK has no canonical provider price catalog.
