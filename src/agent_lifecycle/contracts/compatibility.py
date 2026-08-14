"""Public contract compatibility policy helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schemas import list_schemas

POLICY_SCHEMA_VERSION = "agent-public-contract-policy.v1"
VALIDATION_SCHEMA_VERSION = "agent-public-contract-policy-validation.v1"

DEPRECATED_COMPATIBLE_SCHEMAS: dict[str, dict[str, str]] = {
    "agent-lifecycle-host-model-profile.v1": {
        "replacement": "agent-host-model-selection-profile.v1",
        "behavior": "accepted-compatible",
    },
}

CLI_OUTPUTS: tuple[dict[str, str], ...] = (
    {"command": "version", "schemaVersion": "agent-lifecycle-version.v1", "compatibility": "stable-json"},
    {"command": "schema list", "schemaVersion": "agent-lifecycle-schema-index.v1", "compatibility": "stable-json"},
    {"command": "schema show", "schemaVersion": "<requested-schema>", "compatibility": "stable-json"},
    {"command": "contract policy", "schemaVersion": POLICY_SCHEMA_VERSION, "compatibility": "stable-json"},
    {"command": "contract check", "schemaVersion": VALIDATION_SCHEMA_VERSION, "compatibility": "stable-json"},
    {"command": "metrics cost-check", "schemaVersion": "agent-lifecycle-cost-validation.v1", "compatibility": "stable-json"},
    {"command": "metrics cost-report", "schemaVersion": "agent-lifecycle-cost-generation.v1", "compatibility": "stable-json"},
    {"command": "metrics outcome-index", "schemaVersion": "agent-task-outcome-index.v1", "compatibility": "stable-json"},
    {"command": "metrics quality-signals", "schemaVersion": "agent-quality-cost-signals.v1", "compatibility": "stable-json"},
    {"command": "metrics recommend", "schemaVersion": "agent-lifecycle-recommendation.v1", "compatibility": "stable-json"},
    {"command": "metrics learn-recommend", "schemaVersion": "agent-lifecycle-recommendation.v1", "compatibility": "stable-json"},
    {"command": "benchmark evaluate", "schemaVersion": "agent-reference-task-evaluation.v1", "compatibility": "stable-json"},
    {"command": "benchmark compare", "schemaVersion": "agent-reference-task-comparison.v1", "compatibility": "stable-json"},
    {"command": "benchmark sample", "schemaVersion": "agent-benchmark-stratified-sample.v1", "compatibility": "stable-json"},
    {"command": "benchmark receipt-check", "schemaVersion": "agent-benchmark-run-receipt-validation.v1", "compatibility": "stable-json"},
    {"command": "benchmark qualify", "schemaVersion": "agent-benchmark-qualification.v1", "compatibility": "stable-json"},
    {"command": "benchmark compare-routes", "schemaVersion": "agent-benchmark-route-comparison.v1", "compatibility": "stable-json"},
    {"command": "strategy resolve", "schemaVersion": "agent-execution-strategy.v1", "compatibility": "stable-json"},
    {"command": "policy tune", "schemaVersion": "agent-lifecycle-policy-tune-result.v1", "compatibility": "stable-json"},
    {"command": "policy runtime-receipt", "schemaVersion": "agent-runtime-policy-receipt.v1", "compatibility": "stable-json"},
    {"command": "policy runtime-check", "schemaVersion": "agent-runtime-policy-receipt-validation.v1", "compatibility": "stable-json"},
    {"command": "policy adaptive-decision", "schemaVersion": "agent-adaptive-lifecycle-policy-decision.v1", "compatibility": "stable-json"},
    {"command": "policy adaptive-check", "schemaVersion": "agent-adaptive-lifecycle-policy-decision-validation.v1", "compatibility": "stable-json"},
    {"command": "evidence index", "schemaVersion": "agent-evidence-index.v1", "compatibility": "stable-json"},
    {"command": "evidence search", "schemaVersion": "agent-evidence-search-summary.v1", "compatibility": "stable-json"},
    {"command": "import plan", "schemaVersion": "agent-planning-import-result.v1", "compatibility": "stable-json"},
    {"command": "import check", "schemaVersion": "agent-planning-import-validation.v1", "compatibility": "stable-json"},
    {"command": "import proposal-check", "schemaVersion": "agent-skill-improvement-proposal-validation.v1", "compatibility": "stable-json"},
    {"command": "plan completeness-check", "schemaVersion": "agent-plan-completeness-validation.v1", "compatibility": "stable-json"},
    {"command": "plan delta", "schemaVersion": "agent-plan-delta.v1", "compatibility": "stable-json"},
    {"command": "plan delta-check", "schemaVersion": "agent-plan-delta-validation.v1", "compatibility": "stable-json"},
    {"command": "quality template-list", "schemaVersion": "agent-task-template-library.v1", "compatibility": "stable-json"},
    {"command": "quality template-check", "schemaVersion": "agent-task-template-library-validation.v1", "compatibility": "stable-json"},
    {"command": "quality bug-recipe-list", "schemaVersion": "agent-bug-forensics-recipe-library.v1", "compatibility": "stable-json"},
    {"command": "quality bug-recipe-check", "schemaVersion": "agent-bug-forensics-recipe-validation.v1", "compatibility": "stable-json"},
    {"command": "audit implementation", "schemaVersion": "agent-implementation-audit-report.v1", "compatibility": "stable-json"},
    {"command": "audit final-implementation", "schemaVersion": "agent-final-implementation-audit.v1", "compatibility": "stable-json"},
    {"command": "audit package", "schemaVersion": "agent-plan-package-audit-report.v1", "compatibility": "stable-json"},
    {"command": "report status-view", "schemaVersion": "agent-readonly-status-view.v1", "compatibility": "stable-json"},
    {"command": "report event-feed", "schemaVersion": "agent-workflow-event-feed.v1", "compatibility": "stable-json"},
    {"command": "report progress", "schemaVersion": "agent-lifecycle-progress-view.v1", "compatibility": "stable-json"},
    {"command": "report progress --watch", "schemaVersion": "agent-lifecycle-progress-watch.v1", "compatibility": "stable-json"},
    {"command": "report progress-bridge", "schemaVersion": "agent-progress-bridge-receipt.v1", "compatibility": "stable-json"},
    {"command": "report change-summary", "schemaVersion": "agent-change-summary-receipt.v1", "compatibility": "stable-json"},
    {"command": "context checkpoint", "schemaVersion": "agent-context-checkpoint.v1", "compatibility": "stable-json"},
    {"command": "context restore", "schemaVersion": "agent-context-continuation.v1", "compatibility": "stable-json"},
    {"command": "context continuation", "schemaVersion": "agent-context-continuation.v1", "compatibility": "stable-json"},
    {
        "command": "workflow run",
        "schemaVersion": "agent-managed-lifecycle-runner-receipt.v1",
        "compatibility": "stable-json",
    },
    {
        "command": "workflow * --progress-hook receipt",
        "schemaVersion": "agent-progress-hook-receipt.v1",
        "compatibility": "explicit-side-receipt-json",
    },
    {"command": "adapter session start", "schemaVersion": "agent-adapter-session-receipt.v1", "compatibility": "stable-json"},
    {"command": "adapter session status", "schemaVersion": "agent-adapter-session-receipt.v1", "compatibility": "stable-json"},
    {"command": "adapter session promote", "schemaVersion": "agent-adapter-session-receipt.v1", "compatibility": "stable-json"},
    {"command": "adapter session resume", "schemaVersion": "agent-adapter-session-resume-receipt.v1", "compatibility": "stable-json"},
    {"command": "adapter run", "schemaVersion": "agent-adapter-session-receipt.v1", "compatibility": "stable-json"},
    {"command": "adapter task start", "schemaVersion": "agent-adapter-task-start-receipt.v1", "compatibility": "stable-json"},
    {"command": "thread request", "schemaVersion": "agent-thread-operation-request.v1", "compatibility": "stable-json"},
    {"command": "thread import", "schemaVersion": "agent-thread-context-import.v1", "compatibility": "stable-json"},
    {"command": "project profile check", "schemaVersion": "agent-effective-project-workflow-profile.v1", "compatibility": "stable-json"},
    {"command": "project principles check", "schemaVersion": "agent-project-principles-validation.v1", "compatibility": "stable-json"},
    {"command": "start --project-profile", "schemaVersion": "agent-guided-action-receipt.v1", "compatibility": "stable-json"},
    {"command": "adapter launch-profile", "schemaVersion": "agent-qualified-launch-profile-generation.v1", "compatibility": "stable-json"},
    {"command": "start", "schemaVersion": "agent-lifecycle-start-receipt.v1", "compatibility": "stable-json"},
    {
        "command": "start --launch (planning)",
        "schemaVersion": "agent-lifecycle-start-receipt.v1",
        "compatibility": "stable-json",
    },
    {
        "command": "host-launch inspect",
        "schemaVersion": "agent-local-host-launch-profile-receipt.v1",
        "compatibility": "stable-json",
    },
    {
        "command": "host-launch preflight",
        "schemaVersion": "agent-local-host-launch-profile-receipt.v1",
        "compatibility": "stable-json",
    },
    {"command": "review-mesh profile", "schemaVersion": "agent-review-mesh-profile.v1", "compatibility": "stable-json"},
    {"command": "review-mesh recommend", "schemaVersion": "agent-review-mesh-recommendation.v1", "compatibility": "stable-json"},
    {"command": "specification completion-gate", "schemaVersion": "agent-completion-gate-receipt.v1", "compatibility": "stable-json"},
    {"command": "task compile-small", "schemaVersion": "agent-small-model-packet-compile-result.v1", "compatibility": "stable-json"},
)

REQUIRED_CORE_SCHEMAS: tuple[str, ...] = (
    "agent-lifecycle-error.v1",
    "agent-lifecycle-schema-index.v1",
    "agent-completion-check.v1",
    "agent-completion-check-receipt.v1",
    "agent-completion-gate-receipt.v1",
    "agent-goal-record.v1",
    "agent-follow-up-register.v1",
    "agent-runner-state.v1",
    "agent-adapter-event.v1",
    "agent-review-verdict.v1",
    "agent-task-plan-compatibility-receipt.v1",
    "agent-thread-capability.v1",
    "agent-thread-operation-request.v1",
    "agent-thread-operation-receipt.v1",
    "agent-thread-context-import.v1",
    "agent-thread-operation-validation.v1",
    "agent-thread-bridge-profile.v1",
    "agent-thread-bridge-qualification-receipt.v1",
    "agent-thread-bridge-profile-validation.v1",
)


def build_contract_policy() -> dict[str, Any]:
    """Build the current public compatibility policy from the schema registry."""

    registry_ids = [item["id"] for item in list_schemas()["schemas"]]
    schemas = []
    for schema_id in registry_ids:
        deprecated = DEPRECATED_COMPATIBLE_SCHEMAS.get(schema_id)
        if deprecated:
            schemas.append(
                {
                    "id": schema_id,
                    "status": "DEPRECATED_COMPATIBLE",
                    "compatibility": "accepted-for-reading",
                    **deprecated,
                }
            )
        else:
            schemas.append(
                {
                    "id": schema_id,
                    "status": "STABLE",
                    "compatibility": "additive-compatible",
                }
            )
    body = {
        "schemaVersion": POLICY_SCHEMA_VERSION,
        "status": "PASS",
        "rules": {
            "schemaChanges": "add optional fields or introduce a new schema id; do not change required meaning in-place",
            "cliOutputChanges": "preserve schemaVersion and machine-readable fields; add fields only when older clients can ignore them",
            "deprecations": "keep accepted-compatible readers and document replacement before removal",
            "errors": "return agent-lifecycle-error.v1 with stable code and details",
        },
        "requiredCoreSchemas": list(REQUIRED_CORE_SCHEMAS),
        "schemas": schemas,
        "cliOutputs": [dict(item) for item in CLI_OUTPUTS],
        "productionPromotionClaimed": False,
    }
    return {**body, "policyDigest": canonical_digest(body)}


def validate_contract_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a public contract policy against the current source registry."""

    payload = policy or build_contract_policy()
    registry_ids = {item["id"] for item in list_schemas()["schemas"]}
    blockers: list[dict[str, Any]] = []
    if payload.get("schemaVersion") != POLICY_SCHEMA_VERSION:
        blockers.append({"code": "contract-policy-schema", "message": "unsupported public contract policy schemaVersion"})
    if payload.get("status") != "PASS":
        blockers.append({"code": "contract-policy-status", "message": "public contract policy status must be PASS"})
    if payload.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "contract-policy-production-claim", "message": "policy must not claim production promotion"})
    _check_policy_rules(payload.get("rules"), blockers)
    schema_rows = payload.get("schemas")
    if not isinstance(schema_rows, list) or not schema_rows:
        blockers.append({"code": "contract-policy-schemas-missing", "message": "schemas must be a non-empty array"})
        schema_rows = []
    schema_ids = _collect_ids(schema_rows, key="id", code="contract-policy-schema-duplicate", blockers=blockers)
    missing_registry = sorted(schema_ids.difference(registry_ids))
    if missing_registry:
        blockers.append({"code": "contract-policy-schema-unknown", "schemas": missing_registry})
    required_missing = sorted(set(REQUIRED_CORE_SCHEMAS).difference(schema_ids))
    if required_missing:
        blockers.append({"code": "contract-policy-core-schema-missing", "schemas": required_missing})
    for row in schema_rows:
        if not isinstance(row, dict):
            blockers.append({"code": "contract-policy-schema-row", "message": "schema rows must be objects"})
            continue
        _check_schema_row(row, registry_ids, blockers)
    cli_outputs = payload.get("cliOutputs")
    if not isinstance(cli_outputs, list) or not cli_outputs:
        blockers.append({"code": "contract-policy-cli-missing", "message": "cliOutputs must be a non-empty array"})
        cli_outputs = []
    _collect_ids(cli_outputs, key="command", code="contract-policy-cli-duplicate", blockers=blockers)
    for row in cli_outputs:
        if not isinstance(row, dict):
            blockers.append({"code": "contract-policy-cli-row", "message": "cli output rows must be objects"})
            continue
        _check_cli_row(row, registry_ids, blockers)
    expected_digest = canonical_digest({k: v for k, v in payload.items() if k != "policyDigest"})
    if payload.get("policyDigest") != expected_digest:
        blockers.append({"code": "contract-policy-digest", "message": "policyDigest does not match policy body"})
    body = {
        "schemaVersion": VALIDATION_SCHEMA_VERSION,
        "status": "PASS" if not blockers else "FAIL",
        "schemaCount": len(schema_rows),
        "cliOutputCount": len(cli_outputs),
        "deprecatedCompatibleSchemas": sorted(DEPRECATED_COMPATIBLE_SCHEMAS),
        "blockers": blockers,
        "policyDigest": payload.get("policyDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_contract_policy_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") == "FAIL":
        raise LifecycleError("contract-policy-validation-failed", "public contract policy validation failed", {"validation": validation})
    return validation


def _check_policy_rules(rules: Any, blockers: list[dict[str, Any]]) -> None:
    required = {"schemaChanges", "cliOutputChanges", "deprecations", "errors"}
    if not isinstance(rules, dict):
        blockers.append({"code": "contract-policy-rules", "message": "rules must be an object"})
        return
    missing = sorted(required.difference(rules))
    if missing:
        blockers.append({"code": "contract-policy-rule-missing", "rules": missing})
    for key in required.intersection(rules):
        if not isinstance(rules.get(key), str) or not rules[key]:
            blockers.append({"code": "contract-policy-rule-empty", "rule": key})


def _collect_ids(rows: list[Any], *, key: str, code: str, blockers: list[dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get(key)
        if not isinstance(value, str) or not value:
            blockers.append({"code": f"{code}-missing", "field": key})
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        blockers.append({"code": code, "values": sorted(duplicates)})
    return seen


def _check_schema_row(row: dict[str, Any], registry_ids: set[str], blockers: list[dict[str, Any]]) -> None:
    status = row.get("status")
    if status not in {"STABLE", "DEPRECATED_COMPATIBLE"}:
        blockers.append({"code": "contract-policy-schema-status", "schema": row.get("id"), "status": status})
    if not isinstance(row.get("compatibility"), str) or not row["compatibility"]:
        blockers.append({"code": "contract-policy-schema-compatibility", "schema": row.get("id")})
    if status == "DEPRECATED_COMPATIBLE":
        replacement = row.get("replacement")
        if replacement not in registry_ids:
            blockers.append({"code": "contract-policy-deprecation-replacement", "schema": row.get("id"), "replacement": replacement})
        if row.get("behavior") != "accepted-compatible":
            blockers.append({"code": "contract-policy-deprecation-behavior", "schema": row.get("id")})


def _check_cli_row(row: dict[str, Any], registry_ids: set[str], blockers: list[dict[str, Any]]) -> None:
    schema_version = row.get("schemaVersion")
    if schema_version != "<requested-schema>" and schema_version not in registry_ids:
        blockers.append({"code": "contract-policy-cli-schema", "command": row.get("command"), "schemaVersion": schema_version})
    if row.get("compatibility") not in {"stable-json", "explicit-side-receipt-json"}:
        blockers.append({"code": "contract-policy-cli-compatibility", "command": row.get("command")})
