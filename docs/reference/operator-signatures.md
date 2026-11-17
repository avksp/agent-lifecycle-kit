# Operator signatures

ALK can check public detached Ed25519 signatures before a plan freeze,
execution authorization, or final run acceptance. The feature is off by
default. It adds a check to existing gates. It does not replace plan review,
execution permission, task acceptance, final audit, or release verification.

## Choose a mode

| Mode | Behaviour |
| --- | --- |
| Omitted or `off` | No signature lookup and no signature fields in existing receipts. |
| `advisory` | Report the verification result. An invalid signature alone does not block the action. |
| `required` | Refuse an invalid, missing, expired, or mismatched signature before protected writes. |

Malformed policy is an error in every mode. Other lifecycle gates remain in
force in advisory mode. A valid signature alone grants no native permission.

Use `operatorSignaturePolicy` with schema
`agent-operator-signature-policy.v1`. An explicit off policy contains only
`schemaVersion` and `mode`. Active policies also contain a `trustRoot` with
schema `agent-operator-trust-root.v1`, a `rootId`, and one to sixteen public
keys. Each key has these fields:

- `publicKeyHex`: 32 public-key bytes as lowercase hexadecimal.
- `fingerprint`: `ed25519:` followed by SHA-256 of the public-key bytes.
- `validFrom` and `expiresAt`: UTC timestamps such as
  `2026-11-17T00:00:00.000000Z`.

Sort keys by fingerprint. Duplicate keys, unknown fields, and empty validity
intervals are invalid. ALK reads public data only. It has no signer, private-key
input, key-generation command, or key-custody service. Arrange signing outside
the agent-facing CLI; protect that signer with controls appropriate to your
environment.

Required mode also needs whole-package integrity and an exact
`operatorSignatureAuthority` marker. Its schema is
`agent-operator-signature-authority.v1`; `policyDigest` is the canonical digest
of the selected policy, and `stateSchemaVersion` is
`agent-workflow-state.v7`. The marker records a requirement; it is not approval.
Required adoption uses `approval-required`, never automatic authorization.
Set `packageIntegrity.required` to `true` and
`packageIntegrity.lockSchemaVersion` to `agent-plan-lock.v2`. The declaration
stays v2; composite reviewed evidence can produce a derived v3 lock. A v3 lock
is not a supported v3 declaration.

Published JSON schemas describe necessary structural checks. They do not prove
fingerprint derivation, key order, validity at admission, decision-kind field
relationships or cryptographic verification. ALK semantic validators and native
gates remain required; a JSON-schema PASS grants no authority.

## Prepare and sign a decision

The public CLI family is `operator-signature`, with `request` and `verify`
actions. Select `--kind freeze`, `authorize`, or `accept`.

For freeze, supply `--manifest`. For authorize or accept, supply `--state`,
`--subject`, and the exact future `--operation-id`. The subject is the actual
authorization or renewal receipt, or the complete independent final audit.
For freeze, paths resolve from the working directory. For state decisions,
`--state` resolves from the working directory; `--subject`, `--signature` and
`--out` resolve from the state's declared package root.

For `request`, also supply `--signer-fingerprint`, `--valid-from`, and
`--expires-at`. The response contains the public payload and
`signingMessageHex`. It does not sign the request or grant permission.

The signer signs the bytes decoded from `signingMessageHex`. Return a public
envelope with exactly these fields:

```json
{
  "schemaVersion": "agent-operator-signature.v1",
  "payload": {},
  "signatureHex": "128 lowercase hexadecimal characters"
}
```

This illustrates the envelope structure; `{}` is not a valid decision. Preserve
the complete payload returned by `request`. The signature is 64 bytes. Do not
send a private key to ALK.

The authenticated payload binds the decision kind, package and plan revision,
plan and source digests, run and expected state revision, operation ID, complete
subject digest, policy and root digests, signer fingerprint, and validity
interval. Freeze has no run or state revision. Its operation ID is `freeze:`
followed by the prepared manifest digest. ALK reconstructs the expected binding
from actual inputs; envelope fields cannot select another root or subject.

Signing bytes use the domain `agent-lifecycle-operator-{kind}-v1`, a NUL byte,
and the ASCII canonical digest of the complete payload. A signature for one
decision kind cannot authorize another kind.

## Store and verify public evidence

Place the freeze envelope beside the plan manifest as
`operator-freeze-signature.json`. Declare this name in
`packageIntegrity.allowedUnlistedFiles`, not `planFiles`: including the
signature in what it signs would create a digest cycle. Freeze signs the final
prepared manifest. A subsequent manifest edit requires a new reviewed decision.

For authorization or renewal, append `.operator-signature.json` to the exact
receipt path. For final acceptance, append the same suffix to the final-audit
path. These are public, bounded regular repository files; symlinks and malformed
or oversized input are refused. The envelope limit is 1 MiB.

Use `verify` with the same authoritative inputs and `--signature`. Optional
`--out` creates a new public result without replacing an existing file.
Verification is read-only. It does not consume an operation or replace the
signature check at the later native transition. ALK uses its actual UTC clock;
there is no user-selected admission time. Both key eligibility and decision
validity must cover that time; the decision interval must fit inside the key
interval.

The canonical freeze lock binds the exact signature evidence. Read-only checks
can be repeated. Competing freeze publications have one create-only winner.
Authorization, renewal, and finalization retain evidence in their existing
native state, event, or proof. Their run, revision, and operation checks reject
a second committing use. These are local workflow guarantees, not global
cross-clone replay protection.

## Compatibility and recovery

Only required mode selects native state v7. Old and off plans retain existing
formats. Required Review Mesh alone retains v6; combining both required
profiles uses v7 and preserves both distinct authority markers. Older readers
must refuse v7. A lock from an older writer without required signature evidence
does not become valid by using a familiar lock schema.

ALK does not add same-run removal, root replacement, mode downgrade, or
migration from v7 to an older format. If a bound freeze signature expires, use
the existing reviewed revision and refreeze route. Do not replace its bound
envelope, edit native state, reset a clock, or reuse an old authorization.

The existing workflow kernel can detect an event/state split after an
interrupted commit. It is not a filesystem-wide ACID transaction. Preserve the
failed receipt and use the documented recovery route; do not assume that retry
is safe after an uncertain effect.

## What a result proves

`signatureVerified: true` proves the exact bytes under the selected pinned
public key. The receipt labels that scoped assertion `Externally attested`
and the local check `Enforced locally`. Initial root selection remains
`Declared`; `keyCustodyVerified` and pure verification's
`nativePermissionGranted` remain false.

This does not prove a human identity, independent review quality, secret-key
custody, or host isolation. A process with the same account and write access
can replace files, code, or a whole workspace. See the
[threat model](../architecture/threat-model.md) and
[SDLC boundary](../architecture/sdlc-boundary.md).
