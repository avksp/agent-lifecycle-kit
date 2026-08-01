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
    {"command": "metrics recommend", "schemaVersion": "agent-lifecycle-recommendation.v1", "compatibility": "stable-json"},
    {"command": "policy tune", "schemaVersion": "agent-lifecycle-policy-tune-result.v1", "compatibility": "stable-json"},
    {"command": "evidence index", "schemaVersion": "agent-evidence-index.v1", "compatibility": "stable-json"},
    {"command": "evidence search", "schemaVersion": "agent-evidence-search-summary.v1", "compatibility": "stable-json"},
    {"command": "import plan", "schemaVersion": "agent-planning-import-result.v1", "compatibility": "stable-json"},
    {"command": "import check", "schemaVersion": "agent-planning-import-validation.v1", "compatibility": "stable-json"},
    {"command": "import proposal-check", "schemaVersion": "agent-skill-improvement-proposal-validation.v1", "compatibility": "stable-json"},
    {"command": "quality template-list", "schemaVersion": "agent-task-template-library.v1", "compatibility": "stable-json"},
    {"command": "quality template-check", "schemaVersion": "agent-task-template-library-validation.v1", "compatibility": "stable-json"},
    {"command": "quality bug-recipe-list", "schemaVersion": "agent-bug-forensics-recipe-library.v1", "compatibility": "stable-json"},
    {"command": "quality bug-recipe-check", "schemaVersion": "agent-bug-forensics-recipe-validation.v1", "compatibility": "stable-json"},
)

REQUIRED_CORE_SCHEMAS: tuple[str, ...] = (
    "agent-lifecycle-error.v1",
    "agent-lifecycle-schema-index.v1",
    "agent-completion-check.v1",
    "agent-completion-check-receipt.v1",
    "agent-goal-record.v1",
    "agent-follow-up-register.v1",
    "agent-runner-state.v1",
    "agent-adapter-event.v1",
    "agent-review-verdict.v1",
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
    if row.get("compatibility") != "stable-json":
        blockers.append({"code": "contract-policy-cli-compatibility", "command": row.get("command")})
