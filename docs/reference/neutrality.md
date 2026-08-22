# Neutrality scanning

Neutrality scanning prevents repository-specific secrets, local paths and
host-only material from entering portable release evidence. The default
release scope is `tracked-release`:

```bash
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --require-zero-findings
```

The equivalent module command is `python -m agent_lifecycle.neutrality`.

## Scope selection

| Scope | Source | Intended use |
| --- | --- | --- |
| `tracked-release` | Git index entries from `git ls-files -z --stage --cached` plus the current `HEAD` identity | CI, release candidates and portable source checks. |
| `current-tree-complete` | Regular files found in the working tree | Compatibility with older local checks. Deprecated for release evidence. |
| `full-repository` | Working-tree files plus reachable Git objects | Compatibility with older deep scans. Deprecated for release evidence. |

`tracked-release` does not recurse into submodules. It reads regular files,
reads the payload of a tracked symbolic link without following it, and binds a
gitlink to its staged object id without reading the nested repository. Missing,
unmerged, malformed and unknown index entries make the scan incomplete.

Every tracked path is scanned, including paths that a legacy working-tree scan
would match through `pathExcludes`; tracked content is release content. Git
commands run through the trusted host toolchain with a bounded timeout, and the
worktree and index must remain unchanged during a release scan.

The report binds the selected scope, source class, current revision and a
digest of staged entries in `scopeBinding`. Legacy scopes remain accepted, but
their signed binding contains `deprecatedScope: true`.

## Performance and completeness in 1.78

`tracked-release` remains the normal release route. When a plan explicitly
requires `full-repository`, Git objects are read through bounded batch streams:
the accepted inventory, object IDs, types, sizes and protocol framing are
validated before an object is matched. A timeout, malformed response, limit or
truncated object produces incomplete evidence; the scanner does not silently
drop the object and report a clean partial scan.

Authority and policy deny rules are checked against combined count, length and
aggregate-byte limits before matching. Literal matching preserves rule IDs,
finding order and duplicates; regular expressions retain their separate
semantics. Performance evidence is advisory unless a plan makes a specific
threshold an acceptance criterion. See [performance and resource
budgets](performance-and-resource-budgets.md).

## Local artifacts

Ignored or untracked local evidence is excluded by default. Include it only
when a job explicitly needs it:

```bash
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --include-local-artifacts \
  --require-zero-findings
```

The flag cannot name arbitrary paths. It reads only repository-relative roots
listed in the policy key `localArtifactRoots`. Roots must stay inside the
workspace; symbolic-link traversal is rejected. The inclusion intent, approved
root list, root-set digest, file counters and content digest are part of the
report subject and signed claims.

Use the flag only for a dedicated evidence job. Normal release scans should
remain `tracked-release` without local artifacts.

Declared local roots must exist, remain free of symbolic links and nested
`.git` directories, and fit within `maxLocalArtifactFiles` and
`maxLocalArtifactBytes`. Enumeration is path-sorted so repeated scans of an
unchanged root produce the same digest.

## Stable reads

Each regular file and symbolic-link payload is checked before and after it is
read. If identity changes once, the scanner performs exactly one more read. A
stable second read increments `recoveredReadRaces`; this counter is
informational and is still bound into the signed subject. A second change
increments `readRaces` and `incompleteScans`, excludes unstable bytes and makes
a required-clean scan fail.

Required-clean checks use the canonical `REQUIRED_COMPLETENESS_COUNTERS` set.
They do not reject an otherwise clean report only because
`recoveredReadRaces` is nonzero.

## Signed routes

The same scope choices and local-artifact flag are accepted by `scan`,
`bootstrap` and the controller neutrality gate. Detached receipts and
controller-gate claims bind `scopeBinding`, `deprecatedScope`, the report
subject digest and all required counters. Changing the scope, revision, staged
entry digest, local-artifact intent or approved roots invalidates verification.

Authority files and signing material remain host-supplied. See
[Neutrality authority contract](../security/neutrality-contract.md) for the
trust and create-no-replace rules.
