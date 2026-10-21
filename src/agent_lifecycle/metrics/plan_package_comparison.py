"""Controlled authoring comparisons without inferring model or full-cycle savings."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.contracts.compact_plan_schemas import MAX_COMPACT_OUTPUT_BYTES, load_compact_plan_input
from agent_lifecycle.contracts.ownership_paths import require_manifest_authority_paths
from agent_lifecycle.planning.compact_packages import compile_compact_plan
from agent_lifecycle.planning.traceability import validate_plan_traceability
from agent_lifecycle.planning.validation import validate_plan_manifest


def compare_plan_packages(
    *,
    case_id: str,
    legacy_input: bytes,
    compact_input: bytes,
    compact_source_path: str,
    manifest_path: str,
    source_revision: str,
    source_lineage_digest: str,
    local_elapsed_seconds: dict[str, list[float]] | None = None,
    review_input_bytes: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Compare actual input bytes and all canonical facts, allowing only source-document locations to differ."""
    if not isinstance(case_id, str) or not 1 <= len(case_id) <= 128:
        raise LifecycleError("plan-package-comparison-invalid", "A bounded case identity is required")
    for value, length in ((source_revision, 40), (source_lineage_digest, 64)):
        if not isinstance(value, str) or re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is None:
            raise LifecycleError("plan-package-comparison-invalid", "Exact source revision and lineage are required")
    if not isinstance(legacy_input, bytes) or len(legacy_input) > MAX_COMPACT_OUTPUT_BYTES:
        raise LifecycleError("plan-package-comparison-invalid", "Legacy comparison input exceeds its byte limit")
    legacy = load_json_object(legacy_input, label="controlled verbose manifest")
    compact_source = load_compact_plan_input(compact_input)
    compact = compile_compact_plan(compact_source, source_path=compact_source_path, manifest_path=manifest_path)
    validate_plan_manifest(legacy, require_completeness=True)
    require_manifest_authority_paths(legacy)
    if validate_plan_traceability(legacy)["status"] != "PASS":
        raise LifecycleError("plan-package-comparison-invalid", "Verbose control has invalid canonical traceability")
    if legacy.get("status") != "DRAFT" or legacy["specification"]["tier"] not in {"S0", "S1"}:
        raise LifecycleError("plan-package-comparison-invalid", "Paired inputs must be ordinary S0/S1 authoring drafts")
    legacy_facts, legacy_location = _facts(legacy)
    compact_facts, compact_location = _facts(compact)
    differences = sorted(
        key
        for key in set(legacy_facts) | set(compact_facts)
        if key not in legacy_facts
        or key not in compact_facts
        or canonical_bytes(legacy_facts[key]) != canonical_bytes(compact_facts[key])
    )
    timings = _timings(local_elapsed_seconds)
    review = _review_bytes(review_input_bytes)
    unavailable = {
        "status": "UNAVAILABLE",
        "value": None,
        "reason": "Controlled structural/local observations do not measure comparable real model or workflow runs",
    }
    body = {
        "schemaVersion": "agent-plan-package-comparison.v1",
        "status": "PASS" if not differences else "FAIL",
        "caseId": case_id,
        "workloadClassification": "CONTROLLED",
        "sourceRevision": source_revision,
        "sourceLineageDigest": source_lineage_digest,
        "tier": compact_source["tier"],
        "semanticMismatchFields": differences,
        "sourceDocumentLocationDifferences": {
            "legacy": legacy_location,
            "compact": compact_location,
            "normalizedFieldsOnly": ["specification.source", "planFiles entry equal to specification.source"],
        },
        "canonicalFactsEqual": not differences,
        "qualityScope": "Existing canonical completeness/traceability/authority validation and exact facts only",
        "downstreamAuthorityProofClaimed": False,
        "inputs": {
            "legacy": {"sha256": sha256_hex(legacy_input), "bytes": len(legacy_input), "files": 1},
            "compact": {"sha256": sha256_hex(compact_input), "bytes": len(compact_input), "files": 1},
        },
        "canonicalOutputs": {
            name: {"digest": canonical_digest(value), "bytes": len(canonical_bytes(value)) + 1}
            for name, value in (("legacy", legacy), ("compact", compact))
        },
        "authoringInputByteDelta": len(compact_input) - len(legacy_input),
        "reviewInputBytes": review,
        "localElapsedSeconds": timings,
        "realWorkflowMetrics": {
            name: dict(unavailable)
            for name in (
                "authoringLabor",
                "modelInputTokens",
                "modelOutputTokens",
                "cacheTokens",
                "activeModelSeconds",
                "usdCost",
                "fullCycleSeconds",
            )
        },
        "tokenOrMoneySavingsClaimed": False,
        "productionPromotionClaimed": False,
        "modelCallsStarted": False,
        "limitations": [
            "Byte deltas describe these two supplied authoring documents only; "
            "generated and review inputs are separate.",
            "Caller-supplied local timings exclude unmeasured model, host and full workflow work.",
            "Independent review, stale-lock, execution authorization, task/final audits "
            "and release gates remain separate.",
        ],
    }
    return {**body, "comparisonDigest": canonical_digest(body)}


def _facts(manifest: dict[str, Any]) -> tuple[dict[str, Any], str]:
    value = deepcopy(manifest)
    source = value["specification"].get("source")
    files = value.get("planFiles")
    if not isinstance(source, str) or not isinstance(files, list) or files.count(source) != 1:
        raise LifecycleError(
            "plan-package-comparison-invalid", "Each paired source must have one declared inventory entry"
        )
    value["specification"]["source"] = "<SOURCE_DOCUMENT>"
    value["planFiles"] = sorted("<SOURCE_DOCUMENT>" if item == source else item for item in files)
    return value, source


def _timings(samples: dict[str, list[float]] | None) -> dict[str, Any]:
    if samples is None:
        return {"status": "UNAVAILABLE", "legacy": None, "compact": None}
    if not isinstance(samples, dict) or set(samples) != {"legacy", "compact"}:
        raise LifecycleError("plan-package-comparison-invalid", "Paired local timing samples are required")
    sizes = []
    for values in samples.values():
        if not isinstance(values, list) or not 1 <= len(values) <= 3:
            raise LifecycleError("plan-package-comparison-invalid", "At most three local repetitions are supported")
        if any(type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 60 for value in values):
            raise LifecycleError("plan-package-comparison-invalid", "Local timing samples must be finite seconds")
        sizes.append(len(values))
    if sizes[0] != sizes[1]:
        raise LifecycleError("plan-package-comparison-invalid", "Paired sample counts must match")
    return {"status": "MEASURED_LOCAL_ONLY", **deepcopy(samples)}


def _review_bytes(value: dict[str, int] | None) -> dict[str, Any]:
    if value is None:
        return {"status": "UNAVAILABLE", "legacy": None, "compact": None}
    if (
        not isinstance(value, dict)
        or set(value) != {"legacy", "compact"}
        or any(type(count) is not int or count <= 0 for count in value.values())
    ):
        raise LifecycleError("plan-package-comparison-invalid", "Review byte counts must be explicit positive integers")
    return {"status": "MEASURED", **value}
