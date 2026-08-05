"""Built-in JSON schemas for Review Mesh recommendation receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS
from agent_lifecycle.contracts.schema_builders import open_object_schema

REVIEW_MESH_RECOMMENDATION_SCHEMA = "agent-review-mesh-recommendation.v1"
REVIEW_MESH_RECOMMENDATION_MODES = ("off", *REVIEW_MESH_MODE_IDS)

REVIEW_MESH_RECOMMENDATION_SCHEMAS: dict[str, dict[str, Any]] = {
    REVIEW_MESH_RECOMMENDATION_SCHEMA: open_object_schema(
        REVIEW_MESH_RECOMMENDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "recommendedMode",
            "phaseCoverage",
            "reasons",
            "skipRationale",
            "requiredReviewers",
            "budgetUnits",
            "budgetCap",
            "providerNeutralModelClassHints",
            "modelRoutingClassAvailability",
            "advisoryOnly",
            "requiresOperatorConfirmation",
            "blockingGateActivated",
            "assignmentsGenerated",
            "quorumEnforced",
            "modelCallsStarted",
            "hostLaunchStarted",
            "source",
            "concreteProviderModelNamesInPortableContract",
            "productionPromotionClaimed",
            "recommendationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "recommendedMode": {"enum": list(REVIEW_MESH_RECOMMENDATION_MODES)},
            "phaseCoverage": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "reasons": {"type": "array", "items": {"type": "object"}},
            "skipRationale": {"type": ["string", "null"]},
            "requiredReviewers": {"type": "integer", "minimum": 0},
            "budgetUnits": {"const": "tokens-and-resources"},
            "budgetCap": {"type": "object"},
            "providerNeutralModelClassHints": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "modelRoutingClassAvailability": {"type": "object"},
            "advisoryOnly": {"const": True},
            "requiresOperatorConfirmation": {"const": True},
            "blockingGateActivated": {"const": False},
            "assignmentsGenerated": {"const": False},
            "quorumEnforced": {"const": False},
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "source": {"type": "object"},
            "concreteProviderModelNamesInPortableContract": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "recommendationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}
