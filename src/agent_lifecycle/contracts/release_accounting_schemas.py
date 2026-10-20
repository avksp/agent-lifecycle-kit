"""Schemas for bounded release resource accounting."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.schema_builders import open_object_schema

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}
COMMAND_RESOURCE_SCHEMA = "agent-command-resource-receipt.v1"
COMMANDS = frozenset({
    "version", "start", "host-launch", "diagnose", "diagnostics", "schema",
    "contract", "neutrality", "evidence", "research", "import", "quality",
    "review-mesh", "benchmark", "strategy", "report", "policy", "workflow",
    "audit", "context", "thread", "goal", "followup", "worktree", "model",
    "metrics", "tier", "specification", "plan", "task", "adapter", "project",
    "conformance",
})
PHASES = frozenset({"controller", "model", "review", "remediation", "waiting"})
_SPAN_FIELDS = {
    "schemaVersion", "status", "operationDigest", "sourceRevision", "sourceRevisionBasis",
    "sourceSnapshotDigest", "sourceBinding", "command", "phase", "argvDigest",
    "spanDigest", "parentSpanDigest", "clockDomainDigest", "startWallNs",
    "endWallNs", "startCpuNs", "endCpuNs", "inclusiveWallNs", "exclusiveWallNs",
    "inclusiveCpuNs", "exclusiveCpuNs", "exitCode", "outcome", "childCpu",
    "modelTokens", "children", "authorityClaimed", "productionPromotionClaimed",
    "receiptDigest",
}

RELEASE_ACCOUNTING_SCHEMAS: dict[str, dict[str, Any]] = {
    COMMAND_RESOURCE_SCHEMA: open_object_schema(
        COMMAND_RESOURCE_SCHEMA,
        required=sorted(_SPAN_FIELDS),
        properties={
            "status": {"const": "PASS"},
            "command": {"enum": sorted(COMMANDS)},
            "phase": {"enum": sorted(PHASES)},
            "children": {"type": "array", "maxItems": 64, "items": {"type": "object"}},
            "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    "agent-release-accounting-source.v1": open_object_schema(
        "agent-release-accounting-source.v1",
        required=[
            "schemaVersion",
            "status",
            "releaseId",
            "entryCount",
            "entries",
            "provenance",
            "blockers",
            "productionPromotionClaimed",
            "sourceDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "releaseId": {"type": "string", "minLength": 1, "maxLength": 256},
            "entryCount": {"type": "integer", "minimum": 1, "maximum": 1024},
            "entries": {"type": "array", "minItems": 1, "maxItems": 1024, "items": {"type": "object"}},
            "workflowEconomics": {"type": "object"},
            "provenance": {"type": "object"},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "sourceDigest": _DIGEST,
        },
    ),
    "agent-release-accounting.v1": open_object_schema(
        "agent-release-accounting.v1",
        required=[
            "schemaVersion",
            "status",
            "releaseId",
            "generatedBy",
            "sourceArtifacts",
            "entryCount",
            "entries",
            "views",
            "categoryTotals",
            "totals",
            "exclusions",
            "provenance",
            "blockers",
            "liveCallsStarted",
            "productionPromotionClaimed",
            "accountingDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "releaseId": {"type": "string", "minLength": 1, "maxLength": 256},
            "generatedBy": {"const": "agent-lifecycle metrics release-accounting"},
            "sourceArtifacts": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"type": "object"}},
            "entryCount": {"type": "integer", "minimum": 1, "maximum": 1024},
            "entries": {"type": "array", "minItems": 1, "maxItems": 1024, "items": {"type": "object"}},
            "views": {"type": "object"},
            "categoryTotals": {"type": "object"},
            "totals": {"type": "object"},
            "workflowEconomics": {"type": "object"},
            "exclusions": {"type": "array", "items": {"type": "object"}},
            "provenance": {"type": "object"},
            "blockers": _BLOCKERS,
            "liveCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "accountingDigest": _DIGEST,
        },
    ),
    "agent-release-accounting-validation.v1": open_object_schema(
        "agent-release-accounting-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "releaseId",
            "entryCount",
            "blockers",
            "accountingDigest",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "releaseId": {"type": ["string", "null"]},
            "entryCount": {"type": "integer", "minimum": 0},
            "blockers": _BLOCKERS,
            "accountingDigest": {"type": ["string", "null"], "minLength": 64, "maxLength": 64},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    "agent-release-accounting-generation.v1": open_object_schema(
        "agent-release-accounting-generation.v1",
        required=[
            "schemaVersion",
            "status",
            "outputPath",
            "outputBytes",
            "accountingDigest",
            "validation",
            "liveCallsStarted",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "outputPath": {"type": "string", "minLength": 1},
            "outputBytes": {"type": "integer", "minimum": 1},
            "accountingDigest": _DIGEST,
            "validation": {"type": "object"},
            "liveCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
}


def validate_command_resource_receipt(value: Any) -> dict[str, Any]:
    """Check a bounded, complete synchronous span tree without trusting totals."""
    stack: list[tuple[Any, dict[str, Any] | None]] = [(value, None)]
    spans: list[dict[str, Any]] = []
    seen: set[str] = set()
    blockers: list[dict[str, str]] = []
    while stack and len(spans) <= 64:
        span, parent = stack.pop()
        if not isinstance(span, dict) or set(span) != _SPAN_FIELDS:
            blockers.append({"code": "command-span-shape-invalid"})
            break
        digest_fields = (
            "operationDigest", "sourceSnapshotDigest", "argvDigest", "spanDigest",
            "clockDomainDigest", "receiptDigest",
        )
        if any(not _is_digest(span[key]) for key in digest_fields):
            blockers.append({"code": "command-span-identity-invalid"})
            break
        if span["spanDigest"] in seen:
            blockers.append({"code": "command-span-duplicate-or-cycle"})
            break
        seen.add(span["spanDigest"])
        if not _span_values_valid(span):
            blockers.append({"code": "command-span-values-invalid"})
            break
        if parent is not None and (
            span["parentSpanDigest"] != parent["spanDigest"]
            or any(span[key] != parent[key] for key in (
                "sourceRevision", "sourceSnapshotDigest", "clockDomainDigest",
            ))
            or span["startWallNs"] < parent["startWallNs"]
            or span["endWallNs"] > parent["endWallNs"]
            or span["startCpuNs"] < parent["startCpuNs"]
            or span["endCpuNs"] > parent["endCpuNs"]
        ):
            blockers.append({"code": "command-span-parent-invalid"})
            break
        children = span["children"]
        if not isinstance(children, list) or len(children) > 64:
            blockers.append({"code": "command-span-limit"})
            break
        spans.append(span)
        stack.extend((child, span) for child in children)
    if stack or len(spans) > 64:
        blockers.append({"code": "command-span-limit"})
    if not blockers:
        for span in spans:
            if not _span_totals_valid(span):
                blockers.append({"code": "command-span-totals-invalid"})
            body = {key: item for key, item in span.items() if key != "receiptDigest"}
            if canonical_digest(body) != span["receiptDigest"]:
                blockers.append({"code": "command-span-digest-invalid"})
    return {"status": "FAIL" if blockers else "PASS", "blockers": blockers}


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _span_values_valid(span: dict[str, Any]) -> bool:
    revision = span["sourceRevision"]
    numbers = [key for key in span if key.endswith("Ns")]
    return (
        span["schemaVersion"] == COMMAND_RESOURCE_SCHEMA and span["status"] == "PASS"
        and isinstance(span["command"], str) and span["command"] in COMMANDS
        and isinstance(span["phase"], str) and span["phase"] in PHASES
        and isinstance(revision, str) and len(revision) in {40, 64}
        and all(char in "0123456789abcdef" for char in revision)
        and span["sourceBinding"] == "VERIFIED_SELECTED_BYTES"
        and span["sourceRevisionBasis"] == "DECLARED_BASE"
        and (span["parentSpanDigest"] is None or _is_digest(span["parentSpanDigest"]))
        and all(type(span[key]) is int and 0 <= span[key] < (1 << 63) for key in numbers)
        and type(span["exitCode"]) is int and -255 <= span["exitCode"] <= 255
        and span["outcome"] == ("SUCCEEDED" if span["exitCode"] == 0 else "FAILED")
        and span["childCpu"] == {"status": "UNAVAILABLE", "value": None}
        and span["modelTokens"] == {"status": "UNAVAILABLE", "value": None}
        and span["authorityClaimed"] is False
        and span["productionPromotionClaimed"] is False
    )


def _span_totals_valid(span: dict[str, Any]) -> bool:
    children = sorted(span["children"], key=lambda child: child["startWallNs"])
    if any(a["endWallNs"] > b["startWallNs"] for a, b in pairwise(children)):
        return False
    for quantity in ("Wall", "Cpu"):
        inclusive = span[f"end{quantity}Ns"] - span[f"start{quantity}Ns"]
        exclusive = inclusive - sum(child[f"inclusive{quantity}Ns"] for child in children)
        if span[f"inclusive{quantity}Ns"] != inclusive or span[f"exclusive{quantity}Ns"] != exclusive:
            return False
    return True
