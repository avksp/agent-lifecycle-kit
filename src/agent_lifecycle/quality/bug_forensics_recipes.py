"""Reusable recipes for the optional Bug Forensics profile."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.proof_validation import FINDING_SCHEMA, FIX_IMPACT_SCHEMA, ROOT_CAUSE_SCHEMA
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.quality.bug_forensics import (
    BUG_FORENSICS_PROFILE_SCHEMA,
    BUG_HYPOTHESIS_LEDGER_SCHEMA,
    BUG_REPRODUCTION_RECEIPT_SCHEMA,
    DEFAULT_CONTEXT_BUDGET,
    FAILURE_FINGERPRINT_SCHEMA,
    REGRESSION_PROOF_RECEIPT_SCHEMA,
    build_bug_forensics_profile,
    validate_bug_forensics_profile,
)
from agent_lifecycle.quality.cross_check import CROSS_CHECK_RECEIPT_SCHEMA

BUG_FORENSICS_RECIPE_LIBRARY_SCHEMA = "agent-bug-forensics-recipe-library.v1"
BUG_FORENSICS_RECIPE_VALIDATION_SCHEMA = "agent-bug-forensics-recipe-validation.v1"
BUG_FORENSICS_GATE_RECEIPT_SCHEMA = "agent-bug-forensics-gate-receipt.v1"

_MONEY_KEYS = {"costUsd", "cost_usd", "usd", "budgetUsd", "maxUsd", "money", "monetary"}
_KNOWN_RECEIPT_SCHEMAS = {
    BUG_FORENSICS_PROFILE_SCHEMA,
    BUG_REPRODUCTION_RECEIPT_SCHEMA,
    FAILURE_FINGERPRINT_SCHEMA,
    BUG_HYPOTHESIS_LEDGER_SCHEMA,
    REGRESSION_PROOF_RECEIPT_SCHEMA,
    FINDING_SCHEMA,
    ROOT_CAUSE_SCHEMA,
    FIX_IMPACT_SCHEMA,
    CROSS_CHECK_RECEIPT_SCHEMA,
    BUG_FORENSICS_GATE_RECEIPT_SCHEMA,
}

_RECIPE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "recipeId": "issue-classification",
        "stage": "triage",
        "purpose": "Classify the defect shape and decide whether Bug Forensics is required.",
        "inputs": ["symptom", "logs", "risk"],
        "receiptSchemas": [FINDING_SCHEMA, FAILURE_FINGERPRINT_SCHEMA],
        "requiredChecks": ["task explicitly requests bugfix or incident work", "failure traits are stable enough to fingerprint"],
    },
    {
        "recipeId": "reproduction",
        "stage": "reproduce",
        "purpose": "Prove the bug is red before modification and bind artifacts by digest.",
        "inputs": ["failing command", "environment summary", "artifact digests"],
        "receiptSchemas": [BUG_REPRODUCTION_RECEIPT_SCHEMA, FAILURE_FINGERPRINT_SCHEMA],
        "requiredChecks": ["beforeModification is true", "commandStatus is FAIL or ERROR", "artifactDigests are present"],
    },
    {
        "recipeId": "investigation",
        "stage": "diagnose",
        "purpose": "Track hypotheses until one root cause is accepted and the patch remains minimal.",
        "inputs": ["failure fingerprint", "suspect scope", "changed files"],
        "receiptSchemas": [BUG_HYPOTHESIS_LEDGER_SCHEMA, ROOT_CAUSE_SCHEMA],
        "requiredChecks": ["accepted and rejected hypotheses exist", "outside suspect scope changes have justifications"],
    },
    {
        "recipeId": "validation",
        "stage": "prove",
        "purpose": "Prove red-to-green behavior for the same fingerprint and no collateral damage.",
        "inputs": ["before command", "after command", "fix impact"],
        "receiptSchemas": [REGRESSION_PROOF_RECEIPT_SCHEMA, FIX_IMPACT_SCHEMA],
        "requiredChecks": ["same fingerprint before and after", "neighboring checks are recorded", "collateral damage status is PASS"],
    },
    {
        "recipeId": "review",
        "stage": "review",
        "purpose": "Validate the whole Bug Forensics gate and optional cross-check when the plan requires it.",
        "inputs": ["gate receipt", "review verdict", "optional cross-check"],
        "receiptSchemas": [BUG_FORENSICS_GATE_RECEIPT_SCHEMA, CROSS_CHECK_RECEIPT_SCHEMA],
        "requiredChecks": ["gate is PASS or SKIPPED", "blocking cross-check appears only when explicitly requested"],
    },
)


def build_bug_forensics_recipe_library() -> dict[str, Any]:
    """Return the built-in Bug Forensics recipe catalog."""

    profile = build_bug_forensics_profile()
    recipes = [_recipe_record(spec) for spec in _RECIPE_SPECS]
    body = {
        "schemaVersion": BUG_FORENSICS_RECIPE_LIBRARY_SCHEMA,
        "status": "OPTIONAL",
        "profileId": "bug-forensics",
        "enabledByDefault": False,
        "activationMode": "explicit-task-trigger",
        "reusesExistingReceiptSchemas": True,
        "competingReceiptSchemas": [],
        "defaultLiveCalls": 0,
        "budgetUnits": "tokens-and-resources",
        "contextBudget": dict(DEFAULT_CONTEXT_BUDGET),
        "profileDigest": profile["profileDigest"],
        "recipes": recipes,
        "productionPromotionClaimed": False,
    }
    return {**body, "libraryDigest": canonical_digest(body)}


def validate_bug_forensics_recipe_library(
    library: dict[str, Any] | None = None,
    *,
    recipe_id: str | None = None,
) -> dict[str, Any]:
    """Validate recipe metadata without executing bug-fix work."""

    selected_library = library or build_bug_forensics_recipe_library()
    blockers: list[dict[str, Any]] = []
    if selected_library.get("schemaVersion") != BUG_FORENSICS_RECIPE_LIBRARY_SCHEMA:
        blockers.append({"code": "bug-forensics-recipe-library-schema-invalid"})
    if selected_library.get("status") != "OPTIONAL":
        blockers.append({"code": "bug-forensics-recipe-library-status-invalid"})
    if selected_library.get("enabledByDefault") is not False:
        blockers.append({"code": "bug-forensics-recipe-library-default-enabled"})
    if selected_library.get("activationMode") != "explicit-task-trigger":
        blockers.append({"code": "bug-forensics-recipe-library-activation-invalid"})
    if selected_library.get("reusesExistingReceiptSchemas") is not True:
        blockers.append({"code": "bug-forensics-recipe-reuse-disabled"})
    if selected_library.get("competingReceiptSchemas") != []:
        blockers.append({"code": "bug-forensics-recipe-competing-schema"})
    if selected_library.get("defaultLiveCalls") != 0:
        blockers.append({"code": "bug-forensics-recipe-live-call-default"})
    if selected_library.get("budgetUnits") != "tokens-and-resources":
        blockers.append({"code": "bug-forensics-recipe-budget-units-invalid"})
    if _contains_money_key(selected_library):
        blockers.append({"code": "bug-forensics-recipe-money-field"})
    if selected_library.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "bug-forensics-recipe-production-claim"})
    profile_validation = validate_bug_forensics_profile(build_bug_forensics_profile())
    if profile_validation.get("status") != "PASS":
        blockers.append({"code": "bug-forensics-recipe-profile-invalid", "validation": profile_validation})
    if selected_library.get("libraryDigest") != canonical_digest(_without_digest(selected_library, "libraryDigest")):
        blockers.append({"code": "bug-forensics-recipe-library-digest-mismatch"})

    recipes = selected_library.get("recipes")
    if not isinstance(recipes, list) or not recipes:
        blockers.append({"code": "bug-forensics-recipe-library-empty"})
        recipes = []
    selected_recipes = [item for item in recipes if recipe_id is None or item.get("recipeId") == recipe_id]
    if recipe_id is not None and not selected_recipes:
        blockers.append({"code": "bug-forensics-recipe-id-unknown", "recipeId": recipe_id})

    reports = [
        _validate_recipe_record(item, index=index)
        for index, item in enumerate(selected_recipes)
        if isinstance(item, dict)
    ]
    for report in reports:
        blockers.extend(report["blockers"])

    body = {
        "schemaVersion": BUG_FORENSICS_RECIPE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "profileId": selected_library.get("profileId"),
        "recipeCount": len(selected_recipes),
        "recipeIds": [item.get("recipeId") for item in selected_recipes if isinstance(item, dict)],
        "reports": reports,
        "blockers": blockers,
        "libraryDigest": selected_library.get("libraryDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_bug_forensics_recipe_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "bug-forensics-recipe-validation-failed",
            "bug-forensics recipe validation failed",
            {"validation": validation},
        )
    return validation


def _recipe_record(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "recipeId": spec["recipeId"],
        "stage": spec["stage"],
        "status": "OPTIONAL",
        "enabledByDefault": False,
        "purpose": spec["purpose"],
        "inputs": list(spec["inputs"]),
        "receiptSchemas": list(spec["receiptSchemas"]),
        "requiredChecks": list(spec["requiredChecks"]),
        "createsCompetingSchema": False,
        "requiresLiveCallByDefault": False,
        "providerSpecificCoreDependency": False,
    }


def _validate_recipe_record(recipe: dict[str, Any], *, index: int) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    recipe_id = recipe.get("recipeId")
    if not isinstance(recipe_id, str) or not recipe_id:
        blockers.append({"code": "bug-forensics-recipe-id-invalid", "index": index})
    elif recipe_id not in {item["recipeId"] for item in _RECIPE_SPECS}:
        blockers.append({"code": "bug-forensics-recipe-id-unknown", "recipeId": recipe_id})
    if recipe.get("status") != "OPTIONAL":
        blockers.append({"code": "bug-forensics-recipe-status-invalid", "recipeId": recipe_id})
    if recipe.get("enabledByDefault") is not False:
        blockers.append({"code": "bug-forensics-recipe-default-enabled", "recipeId": recipe_id})
    if recipe.get("createsCompetingSchema") is not False:
        blockers.append({"code": "bug-forensics-recipe-competing-schema", "recipeId": recipe_id})
    if recipe.get("requiresLiveCallByDefault") is not False:
        blockers.append({"code": "bug-forensics-recipe-live-call-default", "recipeId": recipe_id})
    if recipe.get("providerSpecificCoreDependency") is not False:
        blockers.append({"code": "bug-forensics-recipe-provider-core-dependency", "recipeId": recipe_id})
    _check_string_list(recipe.get("inputs"), "bug-forensics-recipe-inputs-invalid", blockers, recipe_id=recipe_id)
    _check_string_list(recipe.get("requiredChecks"), "bug-forensics-recipe-checks-invalid", blockers, recipe_id=recipe_id)
    schemas = recipe.get("receiptSchemas")
    _check_string_list(schemas, "bug-forensics-recipe-receipts-invalid", blockers, recipe_id=recipe_id)
    if isinstance(schemas, list):
        unknown = sorted(schema for schema in schemas if schema not in _KNOWN_RECEIPT_SCHEMAS)
        if unknown:
            blockers.append({"code": "bug-forensics-recipe-receipt-schema-unknown", "recipeId": recipe_id, "schemas": unknown})
    return {"recipeId": recipe_id, "status": "PASS" if not blockers else "FAIL", "blockers": blockers}


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, recipe_id: Any) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        blockers.append({"code": code, "recipeId": recipe_id})


def _contains_money_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in _MONEY_KEYS or _contains_money_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_money_key(item) for item in value)
    return False


def _without_digest(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return {item_key: value for item_key, value in payload.items() if item_key != key}
