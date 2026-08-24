# Adapter action evidence

Release 1.87 extends the existing adapter-event stream with a bounded evidence
envelope. It explains which ALK request, project profile, effective
configuration, capability declaration and permission decision governed one
adapter operation.

## Evidence fields

An action-evidence envelope contains:

- `userRequestId` and `operationLineage` for the ALK run, task and operation;
- `profileDigest`, `effectiveConfigDigest` and `capabilityDigest`;
- a bounded `permissionDecision` from the host, frozen plan or operator;
- one bounded `toolCategory` such as `command`, `filesystem`, `process` or
  `review`;
- a `resultLink` containing a safe reference and digest.

The envelope is attached to the existing event sequence. It is not a second
event store and it does not grant authority to an adapter or to the model.

## Evidence levels

`GUIDANCE_ONLY` is a declaration that does not prove host enforcement.
`OBSERVED` requires one complete, ordered and redacted chain from request to
result. `ENFORCED` additionally requires host-owned before-action blocking and
after-action evidence. Missing, stale, replayed, reordered or incomplete data
becomes `UNAVAILABLE`; it never promotes a claim.

The bundled adapters remain `GUIDANCE_ONLY` with
`NO_RECOMMENDATION`. Release 1.87 does not change the managed-launch status
`WRAPPER_ONLY`.

## Qualification boundary

Qualification is operation-specific and is checked against the shipped adapter
descriptor. A capability manifest must match that descriptor before ALK
attributes enforceability. A capability declaration cannot promote itself to
`OBSERVED` or `ENFORCED` without the required qualification evidence.

Synthetic fixtures are useful for contract and negative tests, but they return
`NO_RECOMMENDATION` and `GUIDANCE_ONLY`. A live qualification requires the
exact host version, positive and negative evidence, no side effect on denied
actions, complete cleanup and valid lineage.

## Privacy and portability

Portable evidence stores digests, bounded categories and safe result links. It
does not store raw prompts, model reasoning, credentials, local absolute paths
or unredacted host output. The event and result validators reject private
references and unknown sensitive fields before an evidence receipt is accepted.

See also [effective configuration](effective-configuration.md), [public
locators and redaction](public-locators-and-redaction.md) and [optional adapter
lifecycle control](../adapters/lifecycle-control.md).
