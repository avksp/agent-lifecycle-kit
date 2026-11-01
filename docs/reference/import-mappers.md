# Import mappers

Import mappers convert external planning and instruction dialects into ALK
draft artifacts. Imported content is never trusted automatically.

## Supported dialect profiles

- `openspec-planning`: OpenSpec planning documents with spec, proposal,
  capability and change hints.
- `github-spec-kit-planning`: GitHub Spec Kit specifications, plans and task
  breakdowns.
- `bmad-method-planning`: BMAD planning, PRD, architecture and story material.
- `spec-kitty-planning`: Spec Kitty requirement, design, task and verification
  material.
- `external-workflow-generic`: generic workflow-like YAML or JSON with
  step/job/check hints.
- `external-agent-generic`: generic agent/harness-like YAML or JSON with
  role/policy/tool/env hints.
- `constitution-adr`: Constitution or ADR-style documents with principles,
  constraints, decisions and numbered requirements.
- `agents-agentskills`: `AGENTS.md` or agentskills-style instruction files.

Each profile uses `agent-import-dialect-profile.v1` and records:

- `dialectId` and `dialectKind`;
- `sourceTrusted: false`;
- `requiresReview: true`;
- `freezeBlocked: true`;
- `profileDigest`.

## Import behavior

Dialect imports call the same untrusted planning import path as generic imports.
The resulting `agent-planning-import-result.v1` includes
`nativeDialectProfileDigest`, and the candidate plan records the same digest in
`candidatePlan.importState.nativeDialectProfileDigest`.

The candidate plan remains `DRAFT` with review, audit and freeze blockers. The
operator must run normal ALK plan review and freeze before implementation.

Generic external imports add a family/profile layer before draft creation:

```text
parse -> reject secrets -> normalize/redact hints -> draft -> validate -> review/freeze
```

Workflow-family imports map steps/jobs/checks to draft requirements, work hints
and validation hints. The hints are context for review; ALK never executes
imported workflow nodes.

Agent-family imports map role and policy hints to draft requirements. Provider,
model, auth, environment and tool hints are host-local metadata. Their values
are redacted or represented by digests and cannot become portable defaults.

```bash
agent-lifecycle import profile-list
agent-lifecycle import plan --source specs/checkout.md --dialect openspec --out import.json
agent-lifecycle import plan --source specs/ --dialect spec-kit --out import.json
agent-lifecycle import plan --source docs/stories/ --dialect bmad --out import.json
agent-lifecycle import plan --source specs/story.md --dialect spec-kitty --out import.json
agent-lifecycle import external --family workflow --source workflow.yaml --out import.json
agent-lifecycle import external --family agent --source agent.yaml --out import.json
agent-lifecycle import check --candidate import.json
agent-lifecycle import external-check --candidate import.json
```

`import plan --source <folder>` reads only Markdown files, sorts them by
relative POSIX path and stores redacted provenance in
`agent-markdown-source-collection.v1`. The receipt contains file labels,
digests and byte counts, but not private absolute paths.

## Python API

```python
from pathlib import Path

from agent_lifecycle.imports import (
    import_bmad_planning,
    import_external_agent,
    import_external_workflow,
    import_markdown_collection,
    import_agentskills_dialect,
    import_constitution_adr,
    import_openspec_planning,
    import_spec_kit_planning,
    import_spec_kitty_planning,
    validate_import_result,
)

result = import_constitution_adr(Path("architecture-decision.md"))
openspec_result = import_openspec_planning(Path("specs/checkout.md"))
spec_kit_result = import_spec_kit_planning(Path("spec.md"))
bmad_result = import_bmad_planning(Path("story.md"))
spec_kitty_result = import_spec_kitty_planning(Path("design.md"))
folder_result = import_markdown_collection(Path("specs"))
workflow_result = import_external_workflow(Path("workflow.yaml"))
agent_result = import_external_agent(Path("agent.yaml"))
validation = validate_import_result(result)
```

## Safety rules

- External dialect input cannot bypass ALK review.
- Local paths and obvious secret markers block import.
- Resource caps apply before candidate generation.
- Profile digest drift fails validation.
- Markdown folder imports use deterministic ordering and bounded file/input
  caps.
- Imported workflow nodes are never executed.
- Provider, model, auth, environment and tool hints from agent-family inputs
  stay host-local and cannot become portable core defaults.

## Tested boundaries and mapper limits

The integration regressions exercise the public import and check commands with
real files. They do not replace the parser, mapper or validators with test
responses. The cases cover these channels and forbidden effects:

| Input channel | Observed boundary |
| --- | --- |
| Markdown instructions, structured planning fields and source labels | Instructions remain draft data; supplied `FROZEN`, trust and freeze claims cannot replace the generated gates. |
| Workflow JSON steps/jobs and the supported YAML-like list form | Commands become review hints; no subprocess or network connection is requested. |
| Agent instructions, provider/model/tool hints and environment metadata | Requirements remain reviewable; host values become digests or key names, without portable provider defaults. |
| Secret-bearing nested metadata, filename, profile ID or package ID | Import fails before writing output; the secret is absent from CLI diagnostics. |
| A generated receipt with altered authority fields and a recomputed digest | The public check command rejects trust, execution, provider-default, review/audit or freeze escalation. A matching digest does not grant authority. |

The effect tests observe `subprocess.Popen`, `os.system` and socket connection
sinks and compare all files in a temporary workspace, including authority and
model-profile sentinels. Successful imports add only the requested draft receipt;
checks leave the workspace unchanged. Benign status-endpoint requirements and
source labels, byte counts, digests and profile bindings have separate assertions.
These are bounded local regressions, not proof against arbitrary model prompt
injection, every host tool or every possible side effect. Imported hostile prose
can still appear as review text. A later host must continue to treat it as data.

Workflow aliases (`steps`/`jobs`, `validation`/`validations`/`checks`) and agent
role/policy mappings have semantic examples in
[`test_external_dialects.py`](../../tests/imports/test_external_dialects.py).
The mapper accepts JSON objects and a limited YAML-like notation, not a general
YAML workflow engine. It keeps at most eight requirements and truncates each to
180 characters; workflow work and validation hints are also capped at eight.
The source digest preserves identity, not a complete semantic translation.
Reviewers must compare the original source before approving scope. Profile
trust/review/freeze checks and digest drift cases are in
[`test_external_dialect_framework.py`](../../tests/imports/test_external_dialect_framework.py);
CLI effect and tampered-receipt cases are in
[`test_untrusted_input_boundaries.py`](../../tests/imports/test_untrusted_input_boundaries.py).

The CI matrix also requires a Node smoke of the actual
[`OpenCode projection`](../../adapters/opencode/plugins/agent-lifecycle-kit.js).
The test parses and imports its bytes as an ES module, checks the exported
function and frozen metadata, and invokes the function to confirm an empty hook
object. One subprocess uses a 15-second limit, 4096 stdout bytes and 8192 stderr
bytes through the existing bounded transport. CI fails if Node is unavailable;
a local skip means that smoke is unproven. This is syntax/export evidence only:
it does not launch OpenCode, Bun or a model, qualify an installed host route, or
change existing OpenCode 1.x/2.x qualification and unsupported-operation limits.

Single-file planning/external imports use stable no-follow reads bounded to the input cap plus one detection byte. Cookie/Set-Cookie values and fine-grained GitHub tokens are sensitive. Lexical normalization preserves ordinary parent-relative paths for those single-file APIs and the external CLI route. Portable path segments are required: symlinks, reparse points, nonregular files and unsafe/nonportable names refuse explicitly. The Markdown collection CLI retains its separate path policy. Overflow inputBytes records detection bytes read, not the total file size.
