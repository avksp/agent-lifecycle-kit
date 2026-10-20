# ALK and the SDLC boundary

ALK controls completion of coding-agent work through explicit authority,
bounded execution, source-bound evidence and acceptance. It connects planning,
implementation and review without becoming another coding-agent runtime.

| Participant | Owns | Does not prove by itself |
| --- | --- | --- |
| ALK core | Contract validation, reviewed locks, native state transitions, gates and evidence identities. | Semantic correctness of model content or universal host enforcement. |
| Host and adapter | Existing tool/model execution, documented host features and command projection. | A stronger guarantee than the tested route supports. |
| Model | Research, proposals, code and review content through host tools. | Independent acceptance of its own output. |
| Repository and CI | Source history, tests, documentation and bound checks on a release candidate. | Runtime behavior of every external adapter or model. |
| User and independent reviewer | Scope decisions, authorization and semantic judgement. | An actual native transition merely by writing its name in prose. |

The sequence remains request → specification/plan → independent review →
reviewed freeze → separate authorization → implementation → task audit → final
audit → finalize. Optional Review Mesh prepares and normalizes review artifacts;
the host or operator must deliver them and retain actual review evidence.

## Strength of a claim

| Level | Required basis |
| --- | --- |
| Designed | A documented requirement or architecture choice; implementation may still be absent. |
| Enforced locally | An actual ALK validator or native transition refuses an invalid input in its stated boundary, with current tests/evidence. |
| Declared | A caller supplies identity, coverage, usage or a judgement; ALK can validate shape/bindings but does not independently observe its truth. |
| Externally attested | A supported route supplies a valid attestation with the required trust boundary and source/operation binding. |

Do not promote one level into another. Valid JSON, schema discovery, a prepared
packet, a caller's coverage list or an independent-looking identifier is not an
attestation. A local index proves that declared bytes were present and matched;
it does not prove that a remote reviewer received or read them.

## Core and adapter maturity

The package's Production/Stable classifier concerns the maintained deterministic
core API and CLI. Offline tests and supported-platform CI provide bounded
evidence for that core. They do not certify all model integrations, deployment
environments, enterprise operation or production promotion. Native adapters
retain their separate `EXPERIMENTAL`/`VERIFIED` support status and host-specific
limits; see [the support matrix](../adapters/support-matrix.md).

Only ALK is adapted. Existing host capabilities determine each route's
admissible guarantees. An unsupported strong mode must refuse explicitly rather
than claim protection from an editable plugin. Current same-account Codex cannot
become an external trusted operator through an ALK declaration.

## Keeping the operator path small

Use [safe artifact authoring](../reference/safe-artifact-authoring.md) for bounded
creation and preflight. Thin skills route to complete preserved contracts;
`tools/release/validate_skill_parity.py` checks their references and actual built
plugin bytes. Small entrypoints reduce mandatory initial text while retaining
the full instructions for the active stage. This is a byte comparison, not a
claim of measured token, monetary or elapsed-time savings.

ALK does not add a model client, provider broker, scheduler or second schema
engine for these helpers. Unknown telemetry remains null. Valid completed work,
expenses, failed attempts and original clocks survive context compaction and
successor plan adoption; evidence is repeated only when invalidated.
