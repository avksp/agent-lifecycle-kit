"""Built-in JSON schema definitions for adapter progress bridge receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

PROGRESS_BRIDGE_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-progress-bridge-config.v1": _open_object_schema(
        "agent-progress-bridge-config.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "supportLevel",
            "hookPoints",
            "displayMode",
            "sourceOfTruth",
            "readOnly",
            "modelCallsStarted",
            "stateWritten",
            "tokenSpendForProgress",
            "hostTelemetryParsedInCore",
            "productionPromotionClaimed",
            "configDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "adapterId": {"type": "string", "minLength": 1},
            "supportLevel": {"enum": ["AUTO", "WATCH", "MANUAL", "UNSUPPORTED"]},
            "hookPoints": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "enum": [
                        "after-workflow-run",
                        "after-task-result",
                        "after-task-accept",
                        "after-finalize",
                        "side-terminal-watch",
                        "manual",
                    ]
                },
            },
            "displayMode": {"enum": ["terminal", "json"]},
            "sourceOfTruth": {"const": False},
            "readOnly": {"const": True},
            "modelCallsStarted": {"const": False},
            "stateWritten": {"const": False},
            "tokenSpendForProgress": {"const": False},
            "hostTelemetryParsedInCore": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "configDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-progress-bridge-receipt.v1": _open_object_schema(
        "agent-progress-bridge-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "supportLevel",
            "hookPoint",
            "displayMode",
            "sourceOfTruth",
            "readOnly",
            "modelCallsStarted",
            "stateWritten",
            "tokenSpendForProgress",
            "tokenCountsInferred",
            "hostTelemetryParsedInCore",
            "terminal",
            "watch",
            "inputCounts",
            "progressIdentity",
            "renderedLines",
            "terminalText",
            "productionPromotionClaimed",
            "bridgeDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "adapterId": {"type": "string", "minLength": 1},
            "supportLevel": {"enum": ["AUTO", "WATCH", "MANUAL", "UNSUPPORTED"]},
            "hookPoint": {
                "enum": [
                    "after-workflow-run",
                    "after-task-result",
                    "after-task-accept",
                    "after-finalize",
                    "side-terminal-watch",
                    "manual",
                ]
            },
            "displayMode": {"enum": ["terminal", "json"]},
            "sourceOfTruth": {"const": False},
            "readOnly": {"const": True},
            "modelCallsStarted": {"const": False},
            "stateWritten": {"const": False},
            "tokenSpendForProgress": {"const": False},
            "tokenCountsInferred": {"const": False},
            "hostTelemetryParsedInCore": {"const": False},
            "terminal": {"type": "boolean"},
            "watch": {"type": "boolean"},
            "inputCounts": {"type": "object"},
            "progressIdentity": {"type": "object"},
            "renderedLines": {"type": "array", "items": {"type": "string"}},
            "terminalText": {"type": "string", "minLength": 1},
            "productionPromotionClaimed": {"const": False},
            "bridgeDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}
