# Source of truth

This project keeps each lifecycle claim in one authoritative layer. Reference
documents may summarize the state, but they should link back to these files
instead of duplicating long rules.

| Claim | Source |
| --- | --- |
| Package version | `pyproject.toml`, `src/agent_lifecycle/_version.py`, `uv.lock` |
| Plugin package version | Root and adapter plugin manifests |
| Public schema ids | `src/agent_lifecycle/contracts/schemas.py` |
| CLI command behavior | `src/agent_lifecycle/cli/` and command tests |
| External issue intake | `skills/issue-to-spec/SKILL.md` and reviewed ALK plans |
| Adapter maturity | `adapters/*/adapter.descriptor.json` |
| Adapter capabilities | `adapters/*/capabilities.manifest.json` |
| Support summary | `docs/adapters/support-matrix.md` |
| Tracked redacted adapter evidence | `docs/adapters/evidence/adapter-evidence-summary.v1.json` and linked summaries |
| Raw live receipts | Host-local ignored evidence paths referenced by adapter descriptors |
| Release history | `CHANGELOG.md` and `release/notes/` |
| Release security boundaries | `docs/security/release-security.md` and security tests |

## Documentation rule

Ordinary docs describe the current behavior. They should not say when a feature
was introduced; the changelog and release notes carry that history.

## Evidence rule

Tracked evidence summaries are suitable for source releases. Local raw receipts
are useful for re-running live promotion review, but they may be absent from a
fresh checkout by design.

## Intake rule

External issues, tickets and imported tracker payloads are draft inputs. They
can seed a specification, but they cannot authorize execution, freeze a plan or
override reviewed ALK source-of-truth artifacts.
