# Plan review

Narrative verdict: `FROZEN_AFTER_DESCRIPTOR_DERIVATION_REMEDIATION`.
Manifest status: `FROZEN`.

## Preconditions

- `release-1-53` is merged or this package is rebased.
- Existing `agent-lifecycle-model-usage-receipt.v1` remains the acceptance
  authority for S1/S2 runs.
- Reference adapter fixtures are synthetic or redacted; no account data is
  committed.

## Machine precheck

```bash
PYTHONPATH=src python3 -m agent_lifecycle plan check --manifest tasks/release-1-54/plan.manifest.json --require-completeness
PYTHONPATH=src python3 -m agent_lifecycle plan acceptance-check --manifest tasks/release-1-54/plan.manifest.json --acceptance tasks/release-1-54/acceptance-criteria.md
PYTHONPATH=src python3 -m agent_lifecycle plan refs-check --manifest tasks/release-1-54/plan.manifest.json
```

After independent audit changes the manifest to `FROZEN`, append
`plan.lock.json` to `planFiles`, generate it with `plan snapshot`, then rerun
`plan check --lock ... --require-completeness` before implementation.

## Review focus

- Check no adapter parser leaks into portable core.
- Check fallback estimates are conservative and labelled `ESTIMATED`.
- Check live capability claims remain absent without host-specific evidence.
- Check the canonical receipt remains route-bound and redacted.
- Check the existing live-harness parsers are removed as authorities rather
  than copied into three new adapter modules.
- Check descriptor declarations are validated as data and do not make fixture
  parsing equivalent to live qualification.
- Check `_attested()` and canonical receipt validation require the same
  `source: host` plus `status: ATTESTED` predicate.
- Check canonical model-usage output is a sidecar with route/source bindings;
  the existing host-operation receipt stays unchanged.
- Check changed descriptor digests are propagated only to the three matching
  capability manifests and event-stream receipts without changing maturity or
  promotion claims.

## Closed design decisions

- The existing model usage receipt remains canonical; no adapter-specific
  public receipt schema is added.
- Gemini CLI, Kimi Code and Qwen Code are reference normalizers because they
  already contain bounded runner/receipt projections. Their fixture support is
  not a promotion claim.
- Codex, Claude Code and OpenCode remain unproven until release 1.57 performs
  a separate qualified-profile evidence run.
- Exactness is a property of host evidence, not of ALK's estimate algorithm.
- Gemini CLI, Kimi Code and Qwen Code runner and live-harness paths share one
  parser owned by the corresponding adapter. The harness remains an evidence
  producer, not a second parser authority.
- Descriptor normalizer status is declarative and fail-closed. `FIXTURE_ONLY`
  proves parser compatibility only; live attestation requires a later
  host-qualified profile and evidence.
- The exact descriptor block is `usageNormalization` with contract
  `adapter-local-usage-normalizer.v1`, status
  `UNSUPPORTED|FIXTURE_ONLY|QUALIFIED`, path, artifact format and byte limit.
  `QUALIFIED` requires a host range, qualification evidence and
  `acceptedForS1S2: true`; all other states require false.
- Adapter-local modules are loaded by one contained helper under
  `tools/live_hosts`. It resolves only
  `adapters/<declared-adapter>/usage_normalizer.py`, rejects traversal and does
  not add adapter directories to portable package imports.
- `usage_normalizer.py` owns host-stream parsing and canonical model-usage
  sidecar construction. `receipt_normalizer.py` continues to normalize the
  separate host-operation receipt. Neither wraps or duplicates the other.
- A normalizer sidecar must bind operation id, route digest, adapter/host,
  model class/hash and path-free source artifact SHA-256/bytes/format plus the
  normalizer digest. The host-operation receipt remains backward compatible.
- The pre-existing metrics `_attested()` predicate is corrected in WS64-01 to
  require both host source and attested status, matching model-routing receipt
  validation.
- Normalizers parse bounded bytes/events/depth and extract allowlisted numeric
  or session fields only. Raw prompt/response/event content is neither retained
  nor copied to portable output.
- Qwen Code keeps its existing adapter maturity. Its newly moved normalizer is
  independently `FIXTURE_ONLY` until the new implementation digest receives
  qualification evidence; this does not downgrade or broaden the adapter-wide
  claim.
- The English and Russian quick starts are release metadata surfaces. Their
  exact package pins are updated with the canonical package version and checked
  by publication and adoption validators.
- Revision 5 records the independent OpenCode S2 review. The architecture
  reviewer returned `READY_TO_FREEZE`; the security review's only Medium claim
  was rejected by direct JSON extraction because `readOnly intersect writes`
  is empty and `cost_collection.py` is write-owned only. The package is frozen
  with a regenerated integrity lock. Claude and Anthropic were not used.
- Revision 6 reopens the package before implementation because the existing
  documentation gate requires the exact package pin in `README.md`, both
  documentation indexes and both CLI references in addition to the quick
  starts. Those five files are added to `WS64-03`; runtime scope and acceptance
  semantics are unchanged. A focused independent OpenCode re-audit is required
  before refreeze.
- Revision 7 records focused independent re-audit by
  `zai-coding-plan/glm-5.2` and `opencode/deepseek-v4-flash-free`. Both returned
  `READY_TO_FREEZE`, confirmed all seven package-pin surfaces are exclusively
  owned by `WS64-03`, and found no read-only/write collision. The package is
  frozen with a new lock. Claude and Anthropic were not used.
- Revision 8 reopens the package after the full repository test suite proved
  that each changed adapter descriptor invalidates its capability manifest's
  bound descriptor digest. `WS64-02` now owns exactly the Gemini CLI, Kimi Code
  and Qwen Code capability manifests. A focused independent OpenCode re-audit
  is required before refreeze; the prior lock is intentionally stale.
- Revision 9 extends the same ownership remediation to the three conformance
  event-stream receipts. A repository-wide search for each previous descriptor
  digest proved that capability manifests and event-stream receipts are the
  complete set of derived tracked artifacts for the changed descriptors. The
  prior lock remains intentionally stale until focused re-audit passes.
- Revision 10 records focused independent re-audit by OpenCode with
  `zai-coding-plan/glm-5.2` and `opencode/deepseek-v4-flash-free`; both returned
  `READY_TO_FREEZE`. A supplementary Qwen Code audit of the explicit plan packet
  also returned `READY_TO_FREEZE` using its configured `GLM-5.2` model. The
  package is frozen with a regenerated lock. Claude and Anthropic were not used.

## Shared-file authority

- 1.54 owns usage provenance classification and the adapter-normalizer contract.
- 1.57 may add new host normalizers but preserves receipt and fallback semantics.
- 1.58 consumes output measurements and may not reinterpret confidence levels.

## Open questions

No unresolved design question is known. Independent S2 audit must verify that
fixture coverage cannot be mistaken for live host qualification.
