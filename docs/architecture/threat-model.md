# Threat model

[Русская версия](../ru/architecture/threat-model.md)

ALK checks a declared plan and its evidence through supported API and CLI
boundaries. The host runs the agent, tools and model calls. ALK does not create
an operating-system security boundary around that host.

Use this model when you select a control or assess a release claim. Name the
operation, trusted inputs, source revision, host version and available evidence.
An unsupported strong mode must refuse rather than claim protection.

## Assets and trust boundaries

Protect these assets:

* the reviewed manifest, lock, package inventory and accepted source;
* native state, events, operation identities, original clocks and expenses;
* task results, independent reviews and their source and operation bindings;
* public trust roots, signed decisions and the policy that selects them;
* sensitive input, credentials and private keys held outside public evidence.

The public key and trust-root digest are public data. A private key is a
different asset. A path outside the workspace does not prove that the agent
or another process under the same account cannot read that key.

Important boundaries are the reviewed plan versus mutable workspace data,
read-only verification versus a committing transition, the verifier versus a
signer, ALK versus its host, and accepted runtime packages versus their delivery
chain. Do not replace one boundary with a prompt or a caller-supplied boolean.

## Adversaries and limits

| Adversary | Relevant control | Remaining risk |
| --- | --- | --- |
| An erring agent | Typed inputs, exact lineage, ownership and native gates reject covered mistakes. | A passing validator does not establish that the proposed product solution is correct. |
| An agent that tries to bypass a gate | Covered native transitions check current state and required evidence. | An agent may use a different runtime, edit raw files or act outside ALK. A skill cannot prevent those actions. |
| Another process under the same account | Stable reads, process locks, digests and signature checks constrain their stated operations. | These controls do not isolate files, keys or executable code from that account. |
| A compromised reviewer route | Independent roles, source binding, evidence checks and explicit dissent limit acceptance. | A valid report or signature can still contain a wrong judgement. |
| A supply-chain attacker | Source-bound CI, protected delivery and package-content checks establish their recorded lineage. | A compromised verifier or trust root can invalidate its own conclusions. An unsigned hash alone does not prove origin. |

## Strength of a claim

Use the four levels defined in [the SDLC boundary](sdlc-boundary.md):

| Level | Meaning |
| --- | --- |
| Designed | A documented requirement or design; implementation may be absent. |
| Enforced locally | A current ALK validator or native transition refuses an invalid input within its stated boundary. |
| Declared | A caller supplies a claim whose truth ALK does not independently observe. |
| Externally attested | A supported route supplies a valid attestation with the required trust boundary and source/operation binding. |

These levels are not the adapter levels `GUIDANCE_ONLY`, `OBSERVED` and
`ENFORCED`. An ALK refusal can be enforced locally without preventing a host
action. A signature authenticates exact bytes under a selected key; it does
not establish who selected that key, custody, reviewer honesty or host isolation.

## Control map

The entries below describe bounded mechanisms. Their current tests and exact
inputs must support the claim made for a specific operation.

| Control | Strength and boundary | Code reference |
| --- | --- | --- |
| Reviewed package integrity | Enforced locally for the manifest, independent-review binding and declared file inventory. | [package_integrity.py](../../src/agent_lifecycle/freeze/package_integrity.py) |
| State and operation admission | Enforced locally for expected revision, unused operation identity and covered native commits. | [operation_kernel.py](../../src/agent_lifecycle/workflow/operation_kernel.py) |
| Concurrent native mutations | Enforced locally for cooperating ALK operations under the selected process lock. | [transactions.py](../../src/agent_lifecycle/workflow/transactions.py) |
| Authority file reads and writes | Enforced locally for the validated path, stable input and bounded output rules. | [authority_io.py](../../src/agent_lifecycle/contracts/authority_io.py) |
| Signed statements and public pins | Enforced locally for strict signature and binding checks; custody and initial root provenance remain separate. | [workflow_authority.py](../../src/agent_lifecycle/contracts/workflow_authority.py) |
| Review provenance | Declared unless the selected route supplies the qualified external basis required for Externally attested. | [provenance.py](../../src/agent_lifecycle/review/provenance.py) |
| Resource receipts | Declared or limited to the qualified observed sources; unavailable whole-host usage remains unknown. | [declared_ledger.py](../../src/agent_lifecycle/accounting/declared_ledger.py); [accounting boundary](../reference/source-native-workflow-accounting.md) |
| Host action control | Designed, Declared or externally supported as the actual route establishes; local package checks alone do not prevent host actions. | [lifecycle_control.py](../../src/agent_lifecycle/adapter_sessions/lifecycle_control.py); [host capabilities](../reference/host-capabilities.md) |

The signed-authority helpers explicitly keep cryptographic data validation
separate from native permission. Nonempty signature text, valid JSON and a
`PASS` label do not establish a trusted operator decision. A selected signature
profile must name its root, exact subject, operation and replay boundary.

## Failure and evidence rules

Reject a missing, stale, substituted or mismatched required input before the
protected mutation. Retain failures and original clocks. Use the existing
recovery route after an uncertain commit; do not automatically repeat an effect.
The event/state protocol is not a filesystem-wide ACID or power-loss guarantee.

Keep source checks, native acceptance, CI, publication and installed-consumer
proof separate. Tests with public synthetic keys prove their stated mechanism;
they do not prove real-world private-key custody or independent host isolation.
Record both the useful proof and its limit.

ALK does not promise model honesty, complete prompt-injection prevention,
unobserved host inactivity, universal sensitive-data detection, or complete
token and cost metering without a qualified source. Keep missing telemetry
unknown. See [source of truth](../reference/source-of-truth.md) and
[implementation audit](../reference/implementation-audit.md) for acceptance.
