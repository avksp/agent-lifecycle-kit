# Source, Clarification And Preflight

## Authoritative Inputs

- `product-specification-r01.json` and its freeze receipt as immutable prior
  authority, revision 2 plus its r03 rejection as append-only lineage, frozen
  `product-specification-r03.json`, rejected revision 4 plus specification
  review r05, and candidate `product-specification-r05.json` for the
  execution-discovered proof contracts.
- `plan.manifest.json` and the immutable plan files it lists.
- Apache License 2.0 in repository root.
- The clean initial `main` baseline recorded by full commit SHA in the
  manifest.

## Historical Inputs

- External integration payloads may be consulted by the lead as historical
  behavior references only. Their locations, repository identities, commands,
  profiles and project-specific content are not authoritative and must never
  be copied into this repository.
- No external repository history is imported.

## Blocking And Non-Blocking Questions

- Blocking questions: none. Repository name, location, Apache-2.0 licensing and
  the zero-project-information boundary are already decided.
- Non-blocking release publication details such as hosting automation and real
  signing keys are deferred. The implementation must provide verifiable local
  release tooling without publishing remotely.

## Assumptions And Decisions

- The core release is useful even when some surface adapters remain
  `experimental`; maturity must be explicit and evidence-based.
- `git-worktree-v1` is the first change-set provider, behind a versioned
  provider interface.
- External origin-specific deny values and Ed25519 trust roots are injected at
  runtime and are never committed, logged or emitted in evidence. Conformance
  keys exist only inside temporary directories; production signing keys remain
  host-owned.
- Network access is denied by default for core and conformance work. Adapter
  tests use network only under host policy and explicit task contracts.

## Baseline Evidence

- Repository branch: `main`.
- Baseline consists of a minimal README and the unmodified Apache-2.0 license.
- The working tree was clean before this plan package was scaffolded.
- No runtime package, skills, adapters, fixtures or project profiles existed at
  baseline.

## Risk And External Dependency Ledger

| Risk | Control | Owner |
| --- | --- | --- |
| Origin-specific information leaks into code, history, samples or evals | Bootstrap, per-launch/per-attempt and full-release signed neutrality gates | WS-01, WS-05, WS-14, WS-15 |
| Core and adapters become coupled | Import boundaries, host protocol, schema contracts and architecture tests | WS-02, WS-10..WS-13 |
| Resume or freeze accepts stale/forged artifacts | Content addressing, CAS, WAL and negative conformance | WS-03, WS-05, WS-09 |
| Token savings weaken review | Tiered budgets preserve independent freeze reviews and final audit | WS-05, WS-09, WS-15 |
| Adapter claims exceed host proof | Explicit maturity registry and live host conformance requirements | WS-10..WS-13 |
| Release cannot be reproduced | Locked dependencies, deterministic inventory, SBOM and provenance checks | WS-14 |
| Platform lacks atomic exchange | Capability is reported unsupported; no unsafe in-place fallback | WS-05, WS-10..WS-13 |
| Secrets or injected deny values appear in evidence | Redacted envelopes and tests that reject persistence or logging | WS-01, WS-09 |
| A routing fallback weakens capability or reviewer independence | Ordered external profiles, preserved mandatory capabilities and fail-closed selection | WS-05, WS-09 |
| A signature is present but not trusted or bound to the scanned subject | External trust root, key fingerprint, subject/scope hashes and freshness verification | WS-01, WS-15 |
| A neutrality output is reused, partially published, aliased or changes its own scanned subject | Operation-bound absent paths, content-bound primary artifacts, detached receipt published last, create-no-replace and identical verifier recomputation | WS-01, WS-05, WS-14 |
| Archive expansion or a file race makes neutrality incomplete | No-follow handle-relative stable reads plus numeric depth, entry, byte and ratio bounds with fail-closed counters | WS-01, WS-05, WS-14 |
| Repository-controlled or stale external authority is accepted | One bounded fresh signed `NEUTRALITY_*` contract outside workspace, Git, artifact and release roots | WS-01, WS-05, WS-14 |
| Release matrix binds a future or mutable inventory | Matrix and builds bind candidate payload bytes; one atomic generation receives a separate final digest and commit marker | WS-14 |
| A terminal audit attempts to include its own future gate/review or proof | READY_FOR_FINALIZATION, accepted terminal review, AWAITING_FINAL_PROOF, finalization neutrality and acyclic controller CAS/WAL finalization | WS-05, WS-15 |
| A single host impersonates the supported matrix | Nine distinct CI-owned leg receipts plus signed fail-closed aggregate | WS-14 |

## Contract Freeze Record

Specification revision 1: `FROZEN`, retained as prior authority.

Specification revision 2: `REOPENED`, independently rejected by review r03 and
retained as append-only lineage.

Specification revision 3: `FROZEN` through independent review r04 and
`reviews/specification-freeze-r03.json`; it remains immutable prior authority.

Specification revision 4: `REOPENED` subject rejected by independent review
r05. `SPEC-005` through `SPEC-008` remain preserved in that append-only report:
write-once neutrality publication, one exact external authority contract,
candidate-versus-final release identity and acyclic terminal finalization were
not yet decision-complete. No freeze receipt was issued for revision 4.

Specification revision 5: `REOPENED` candidate that introduces neutrality
profile v3, release assembly profile v1 and final-proof profile v2. It requires
a new independent review linked to r05 and a matching specification freeze.

Plan revision 4 is retained with `CHANGES_REQUIRED` review r04. Plan revision
5 was an unfrozen intermediate candidate based on the rejected specification
r04; it is not represented as reviewed or frozen authority. The corrected plan
is `REOPENED`, revision 6; all available earlier review lineage remains
append-only.

Remaining sequence: independent specification r05 review and freeze,
deterministic plan validation, independent full plan r06 review, then
fail-closed plan refreeze. No implementation task may launch before the new
`plan.lock.json` is generated and execution is explicitly reauthorized.
