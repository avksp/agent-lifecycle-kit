# Release security

## Current control map

This map describes controls in the current source tree. A source check, an
optional analysis report and a qualified host operation are different evidence.
None alone proves release readiness or absence of vulnerabilities.

### Runtime controls

| Control | Owner | Check | Limit |
| --- | --- | --- | --- |
| Refuse recognized secrets before import candidates or output, including nested text, labels, family and profile metadata (`import-sensitive-content`). | [planning.py](../../src/agent_lifecycle/imports/planning.py), [external_dialects.py](../../src/agent_lifecycle/imports/external_dialects.py), [shared redaction](../../src/agent_lifecycle/contracts/redaction.py) | [CLI output boundaries](../../tests/cli/test_import_security_boundaries.py), [planning imports](../../tests/imports/test_planning_imports.py) | Shared secret categories and sensitive keys, not detection of every secret or instruction injection. Benign imports remain drafts without execution authority. |
| Bound security-file and Markdown-collection reads; reject links and identity changes. Collect at most `maxFiles + 1` matching entries before sorting; refuse excess without reading file contents. | [security_findings.py](../../src/agent_lifecycle/imports/security_findings.py), [multi_markdown.py](../../src/agent_lifecycle/imports/multi_markdown.py), [authority_io.py](../../src/agent_lifecycle/contracts/authority_io.py) | [security import tests](../../tests/imports/test_security_findings.py), [collection tests](../../tests/imports/test_multi_markdown_imports.py) | Reads use at most the byte cap plus one detection byte; collection reads share the total cap. `security-analysis-import-too-large` is retained. Matching-entry bounds are not a bound on all directory traversal work. |
| Bind the frozen package to its lock before execution and audit. | [freeze package](../../src/agent_lifecycle/freeze), [workflow](../../src/agent_lifecycle/workflow) | [freeze tests](../../tests/freeze) | Integrity and authority checks do not prove that the plan or implementation is semantically correct. |

### CI and source guards

| Control | Owner | Check | Limit |
| --- | --- | --- | --- |
| Static launcher policy follows imported aliases, from-imports, lexical scopes and methods; checks shell policy and bounded process routes. | [launcher validator](../../tools/release/validate_adapter_launcher_security.py) | [launcher mutations](../../tests/release/test_adapter_launcher_security.py), [alias/scope cases](../../tests/release/test_adapter_launcher_security_validator.py) | Recognized AST forms only; no proof for arbitrary dynamic Python or all host tool execution. Runtime identity and redaction remain separate controls. |
| Check immutable Action references, explicit permissions and test discovery. | [CI security validator](../../tools/release/validate_ci_security.py), [CI workflow](../../.github/workflows/ci.yml) | [CI security tests](../../tests/release/test_ci_security_validator.py) | Repository configuration checks do not establish live branch protection, approval or publication success. |
| Reject tracked secret markers, local paths and unsupported adapter claims. | [release security tests](../../tests/security/test_release_security.py) | The security suite runs directly in [CI](../../.github/workflows/ci.yml). | Finite marker checks and declared evidence; not a universal secret scanner or host qualification. |
| Validate release ancestry and publication identity; use PyPI Trusted Publisher via the `pypi` environment. | [publish workflow](../../.github/workflows/publish.yml), [release-ref validator](../../tools/release/validate_release_ref.py) | [release-ref tests](../../tests/release/test_release_ref_validator.py) | Actual environment approval, uploaded artifacts and provenance need current external evidence. Offline source-release generation remains local and does not need credentials or network access. |

### Optional security analysis

The [security analysis profile](../reference/security-analysis-profile.md) is
`OPTIONAL`, disabled by default and separate from the controls above. Its
[owner](../../src/agent_lifecycle/quality/security_analysis.py) and
[acceptance tests](../../tests/workflow/test_security_analysis_profile.py) cover
explicit opt-in, bounded authorization and independent verification for covered
high-severity remediation. Importing a finding does not run a scanner, execute
an exploit or establish vulnerability or production status.

### Host limits

Current Codex support remains ordinary limited operation. Protected closure
and operator routes remain unsupported; `ORDINARY_LIMITED` is not a protected
fallback. The [operator contract](../reference/host-local-token-accounting.md)
and [operator refusal tests](../../tests/cli/test_closing_window_commands.py)
record this boundary. Adapter `GUIDANCE_ONLY` is guidance, not enforcement;
see [action evidence](../reference/adapter-action-evidence.md) and its
[qualification owner](../../src/agent_lifecycle/host_protocol/lifecycle_control_qualification.py).
These controls do not prove resistance to instruction injection on every host.

Host-local environment files used by live harnesses require explicit
`--host-env-allow` and [host environment hygiene](../../tools/release/validate_host_env_hygiene.py)
evidence; [validator tests](../../tests/release/test_host_env_hygiene_validator.py)
cover that bounded route. No private key, token, cookie or local-machine path
belongs in portable release artifacts. Security and resource accounting are
separate gates: neither PASS substitutes for the other.

## Historical release 1.75 contract references

The 1.75 overview described signed neutrality receipts binding
claims, operation and primary artifact, checked Git revision arguments,
redaction, JSON limits, private-file permissions, strict Ed25519 decoding,
plan-lock binding and immutable CI references. Keep the
[neutrality contract](neutrality-contract.md),
[public locators and redaction](../reference/public-locators-and-redaction.md)
and [release architecture](../architecture/release-architecture.md) as the
contract references. Historical 1.74/1.75 publication evidence is not proof for
a current distribution. Production promotion requires external signing and
verification authorities and current evidence; those authorities are not
stored in this repository.
