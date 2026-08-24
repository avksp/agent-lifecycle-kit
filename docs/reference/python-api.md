# Python API

ALK is primarily used through its command-line interface. The Python package
also publishes a small, explicit import surface for integrations that need
deterministic local operations. The list below is the compatibility boundary;
an internal function is not public merely because its name does not start with
an underscore.

## Root package

The root package exports `agent_lifecycle.__version__`. The package version is
the only root-level value promised as a stable import.

## Supported facades

The following package facades and their `__all__` exports are supported:

- `agent_lifecycle.contracts`: `LifecycleError`, `canonical_bytes`,
  `canonical_digest`, `load_json_object`, `is_under_repo_path`,
  `normalize_repo_path`, `read_json_object`, `sha256_hex`,
  `write_json_create`.
- `agent_lifecycle.context`: `build_episode_context`, `check_context`,
  `build_context_checkpoint`, `load_context_profile`,
  `list_context_checkpoints`, `load_context_checkpoint`, `render_context`,
  `restore_context_checkpoint`, `require_context_checkpoint_pass`,
  `validate_context_checkpoint`, `validate_context_profile`,
  `write_context_checkpoint`, `import_thread_context`,
  `build_thread_episode_context`.
- `agent_lifecycle.imports`: `agentskills_profile`, `bmad_profile`,
  `collect_markdown_collection`, `constitution_adr_profile`,
  `external_dialect_profile`, `external_dialect_registry`,
  `import_agentskills_dialect`, `import_bmad_planning`,
  `import_constitution_adr`, `import_external_agent`,
  `import_external_dialect`, `import_external_workflow`,
  `import_markdown_collection`, `import_openspec_planning`,
  `import_planning_input`, `import_planning_text`,
  `import_spec_kit_planning`, `import_spec_kitty_planning`,
  `openspec_profile`, `planning_dialect_profile`,
  `require_dialect_profile_pass`, `require_external_import_pass`,
  `require_external_profile_pass`, `require_import_validation_pass`,
  `require_skill_proposal_pass`, `spec_kit_profile`, `spec_kitty_profile`,
  `validate_agentskills_profile`, `validate_dialect_profile`,
  `validate_external_dialect_profile`, `validate_external_import_result`,
  `validate_import_result`, `validate_skill_improvement_proposal`.
- `agent_lifecycle.planning`: `build_domain_language_continuity`,
  `build_plan_snapshot`, `build_plan_delta`,
  `build_plan_completeness_profile`, `build_task_template_library`,
  `load_plan_completeness_profile`, `reconcile_domain_language_continuity`,
  `reconcile_plan_snapshot`,
  `render_task_template`, `render_plan_handoff`,
  `require_reconciliation_pass`, `require_plan_delta_pass`,
  `require_repository_references_pass`, `require_plan_completeness_pass`,
  `require_task_template_validation_pass`, `resolve_sdd_tier`,
  `validate_acceptance_checklist`, `validate_plan_completeness`,
  `validate_plan_completeness_profile`, `validate_plan_manifest`,
  `validate_plan_delta`, `validate_repository_references`,
  `validate_task_template_library`.
- `agent_lifecycle.project`: `PROJECT_PROFILE_RELATIVE_PATH`,
  `build_domain_language_delta`, `build_default_project_profile`,
  `build_effective_project_profile`,
  `build_preset_profile_draft`, `domain_language_digest`,
  `inspect_project_preset`, `language_terms`, `list_project_presets`,
  `load_domain_language`, `load_project_preset`, `load_project_principles`,
  `load_project_profile`, `merge_preset_defaults`, `merge_project_profile`,
  `normalize_project_profile`, `profile_field_is_explicit`,
  `project_principles_digest`, `project_profile_digest`,
  `render_project_preset`, `validate_domain_language`, `validate_project_preset`,
  `validate_project_principles`, `validate_project_profile`.
- `agent_lifecycle.benchmarks`: `build_benchmark_run_receipt`,
  `load_benchmark_run_receipt`, `validate_benchmark_run_receipt`,
  `compare_reference_task_evaluations`, `compare_qualified_routes`,
  `evaluate_reference_task`, `qualify_benchmark_runs`,
  `build_stratified_sample`, `select_stratified_tasks`,
  `validate_qualified_route_comparison`, `validate_qualification_report`,
  `validate_reference_task_comparison`, `validate_stratified_sample`.
- `agent_lifecycle.neutrality`: `AuthorityBundle`,
  `LEGACY_NEUTRALITY_SCOPES`, `NEUTRALITY_SCOPE_CHOICES`,
  `NeutralityFinding`, `NeutralityReport`, `TRACKED_RELEASE_SCOPE`,
  `load_authority_bundle`, `scan_repository`.

Every supported callable is annotated. The machine-readable source of this
list is `policy/python-public-api.json`; the release validator imports every
listed symbol, checks the facade inventory, checks annotations and verifies
that both language versions document the same entries.

## Example

```python
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.project import validate_project_profile

digest = canonical_digest({"status": "PASS"})
validation = validate_project_profile({"schemaVersion": "agent-project-profile.v1"})
```

The API is local and provider-neutral. Importing it does not contact a model
provider or a network service. CLI commands, JSON schemas and lifecycle
receipts remain the authoritative integration boundary for adapters.

## Verification

Run the API contract check from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 tools/release/validate_public_api.py \
  --policy policy/python-public-api.json \
  --package-root src/agent_lifecycle \
  --english docs/reference/python-api.md \
  --russian docs/ru/reference/python-api.md \
  --evidence work/public-api.json
```

Modules not listed in the policy are implementation details. Existing deep
imports may continue to work for compatibility, but they are not new stable
API commitments unless they are listed above.
