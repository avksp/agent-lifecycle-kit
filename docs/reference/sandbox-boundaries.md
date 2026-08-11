# Sandbox boundaries

Sandbox boundaries are optional, schema-backed runtime evidence for filesystem,
network, process and environment containment. They are separate from git
write-scope governance.

## Boundary split

`agent-worktree-attempt-receipt.v1` proves that a task changed only allowed
repository paths in an isolated worktree. It does not prove that the host
runtime blocked network access, process spawning, environment reads or
filesystem paths outside the repository.

`agent-sandbox-receipt.v1` records runtime containment:

- `filesystem`: host or OS limits outside the allowed runtime filesystem
  boundary.
- `network`: denied, filtered or otherwise governed network access.
- `process`: process spawning and child-process controls.
- `environment`: environment variable and secret exposure controls.
- `enforcement.source`: the authority that enforced the boundary, such as
  `HOST`, `OS`, `CONTAINER`, `ADAPTER`, `EXTERNAL`, `UNKNOWN` or
  `UNSUPPORTED`.

Live host harnesses can optionally pass provider credentials from a private
operator env file. That path is an environment boundary, not adapter metadata:
the operator must name every allowed variable with `--host-env-allow`, the
harness passes only those names to the child host process, and receipts record
only `agent-host-env-file-redacted.v1` metadata. Secret values and full
host-local env-file paths are never valid receipt contents.

Unknown support is explicit. A receipt or adapter capability may validate with
`status: UNKNOWN`, but a high-risk task that requires sandbox evidence accepts
only configured passing statuses, `PASS` by default.

Partial containment is represented inside the same canonical
`agent-sandbox-receipt.v1` envelope. For example, Windows process-tree coverage
can be recorded as `boundaries.process.details.partialContainment` with covered
behavior and limitations. Partial containment derives `sandboxStatus: UNKNOWN`
unless a task policy explicitly accepts that status; it must not be upgraded to
`PASS` just because one boundary is partially declared.

Credential proxy evidence also stays inside sandbox boundary details. Receipts
may record a host-local source class, an attachment boundary, allowed variable
names and a placeholder such as `<credential-proxy>`, but they must not contain
secret values or full private env-file paths.

## Policy

`agent-sandbox-requirement.v1` is fail closed. The default policy requires a
passing sandbox receipt for high-risk task classes such as `S2`, `security`,
`release`, `external-environment`, `architecture` and `performance`.

A task can also opt in directly:

```json
{
  "id": "WS-security-01",
  "tier": "S1",
  "executionPolicy": {
    "sandbox": {
      "required": true,
      "acceptedSandboxStatuses": ["PASS"]
    }
  }
}
```

If sandbox evidence is required and missing, validation returns
`sandbox-receipt-required`. If the receipt is structurally valid but has
`sandboxStatus: UNKNOWN`, validation returns `sandbox-receipt-not-accepted`.
Plans that deliberately accept partial containment can override
`acceptedSandboxStatuses` at task level, for example `["PASS", "UNKNOWN"]`.

## Adapter capabilities

Adapter descriptors and capability manifests use
`agent-sandbox-capability.v1`. Existing adapters currently declare
`status: UNKNOWN` and `verified: false` for sandbox support unless a live
sandbox receipt proves otherwise. This keeps the adapter support level separate
from the OS sandbox claim.

An adapter may become more specific only with evidence for every runtime
boundary and enforcement source. Capability manifests must match the descriptor
field exactly; drift fails validation.

## Public contracts

- `agent-sandbox-receipt.v1`
- `agent-sandbox-receipt-validation.v1`
- `agent-sandbox-requirement.v1`
- `agent-sandbox-requirement-validation.v1`
- `agent-sandbox-capability.v1`
- `agent-sandbox-capability-validation.v1`

None of these contracts claim production promotion. Production promotion still
requires the normal release evidence path.
