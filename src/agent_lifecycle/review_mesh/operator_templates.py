"""Operator-facing Review Mesh templates and local packet preparation."""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.changesets.git_io import run_bounded_command
from agent_lifecycle.changesets.snapshot import capture_task_change_set
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, write_json_create
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.ownership_paths import (
    is_under_authority_path,
    observed_authority_paths,
    repository_authority_name,
    require_output_footprint,
)
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.contracts.review_mesh_schemas import build_response_contract, require_response_contract
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES
from agent_lifecycle.review_mesh.assignments import build_review_mesh_assignment_packet
from agent_lifecycle.review_mesh.contracts import build_review_mesh_profile
from agent_lifecycle.review_mesh.results import import_review_mesh_result

REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA = "agent-review-mesh-operator-template.v1"
REVIEW_MESH_OPERATOR_TEMPLATE_LIBRARY_SCHEMA = "agent-review-mesh-operator-template-library.v1"
REVIEW_MESH_PREPARE_RECEIPT_SCHEMA = "agent-review-mesh-prepare-receipt.v1"

REVIEW_MESH_OPERATOR_TEMPLATE_IDS = (
    "leader-draft-review",
    "parallel-research-synthesis",
    "implementation-audit-panel",
)

_DEFAULT_BUDGET = {
    "maxInvocations": 2,
    "maxInputTokens": 12000,
    "maxOutputTokens": 4000,
    "maxWallSeconds": 900,
}

_TEMPLATES: dict[str, dict[str, Any]] = {
    "leader-draft-review": {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA,
        "templateId": "leader-draft-review",
        "mode": "leader-draft-multi-review",
        "phase": "plan-review",
        "description": "One lead draft is checked by independent reviewers before freeze.",
        "requiredReviewers": 2,
        "defaultReviewers": [
            {"id": "reviewer-a", "role": "plan-reviewer", "modelClass": "strong-reasoning"},
            {"id": "reviewer-b", "role": "risk-reviewer", "modelClass": "strong-reasoning"},
        ],
        "budgetCap": _DEFAULT_BUDGET,
        "independenceRequired": True,
        "independenceDimensions": ["host", "model"],
        "blockingDefault": False,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    },
    "parallel-research-synthesis": {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA,
        "templateId": "parallel-research-synthesis",
        "mode": "parallel-research-synthesis",
        "phase": "research",
        "description": "Independent research packets are prepared before synthesis.",
        "requiredReviewers": 3,
        "defaultReviewers": [
            {"id": "researcher-a", "role": "architecture-researcher", "modelClass": "strong-reasoning"},
            {"id": "researcher-b", "role": "risk-researcher", "modelClass": "strong-reasoning"},
            {"id": "researcher-c", "role": "local-reviewer", "modelClass": "local-strong-review"},
        ],
        "budgetCap": {
            "maxInvocations": 3,
            "maxInputTokens": 16000,
            "maxOutputTokens": 6000,
            "maxWallSeconds": 1200,
        },
        "independenceRequired": True,
        "independenceDimensions": ["host", "model"],
        "blockingDefault": False,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    },
    "implementation-audit-panel": {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA,
        "templateId": "implementation-audit-panel",
        "mode": "implementation-audit-panel",
        "phase": "implementation-audit",
        "description": "Multiple auditors check implementation evidence after task completion.",
        "requiredReviewers": 2,
        "defaultReviewers": [
            {"id": "auditor-a", "role": "implementation-auditor", "modelClass": "strong-reasoning"},
            {"id": "auditor-b", "role": "release-auditor", "modelClass": "strong-reasoning"},
        ],
        "budgetCap": _DEFAULT_BUDGET,
        "independenceRequired": True,
        "independenceDimensions": ["host", "model"],
        "blockingDefault": False,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    },
}


def list_review_mesh_operator_templates() -> dict[str, Any]:
    """Return the built-in operator templates without host execution."""

    templates = [get_review_mesh_operator_template(template_id) for template_id in REVIEW_MESH_OPERATOR_TEMPLATE_IDS]
    body = {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_LIBRARY_SCHEMA,
        "templateIds": list(REVIEW_MESH_OPERATOR_TEMPLATE_IDS),
        "templates": templates,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "libraryDigest": canonical_digest(body)}


def get_review_mesh_operator_template(template_id: str) -> dict[str, Any]:
    """Return one built-in operator template by id."""

    if template_id not in _TEMPLATES:
        raise LifecycleError(
            "review-mesh-template-unknown", "unknown Review Mesh operator template", {"templateId": template_id}
        )
    body = deepcopy(_TEMPLATES[template_id])
    return {**body, "templateDigest": canonical_digest(body)}


def validate_review_mesh_operator_template(template: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(template, dict):
        raise LifecycleError("review-mesh-template-invalid", "Review Mesh operator template must be an object")
    if template.get("schemaVersion") != REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA:
        blockers.append({"code": "review-mesh-template-schema-invalid"})
    template_id = template.get("templateId")
    if template_id not in REVIEW_MESH_OPERATOR_TEMPLATE_IDS:
        blockers.append({"code": "review-mesh-template-id-invalid"})
    if not isinstance(template.get("mode"), str) or not template["mode"]:
        blockers.append({"code": "review-mesh-template-mode-invalid"})
    if not isinstance(template.get("phase"), str) or not template["phase"]:
        blockers.append({"code": "review-mesh-template-phase-invalid"})
    reviewers = template.get("defaultReviewers")
    if not isinstance(reviewers, list) or not reviewers:
        blockers.append({"code": "review-mesh-template-reviewers-invalid"})
    else:
        for reviewer in reviewers:
            try:
                _reviewer_from_mapping(reviewer)
            except LifecycleError as error:
                blockers.append({"code": "review-mesh-template-reviewer-invalid", "error": error.code})
    if (
        not isinstance(template.get("requiredReviewers"), int)
        or isinstance(template.get("requiredReviewers"), bool)
        or template["requiredReviewers"] < 1
    ):
        blockers.append({"code": "review-mesh-template-required-reviewers-invalid"})
    if not isinstance(template.get("budgetCap"), dict):
        blockers.append({"code": "review-mesh-template-budget-invalid"})
    for field in ("hostExecutionStarted", "modelCallsStarted", "providerBrokerStarted", "productionPromotionClaimed"):
        if template.get(field) is not False:
            blockers.append({"code": "review-mesh-template-boundary-invalid", "field": field})
    expected_digest = canonical_digest({key: value for key, value in template.items() if key != "templateDigest"})
    if template.get("templateDigest") != expected_digest:
        blockers.append({"code": "review-mesh-template-digest-mismatch"})
    body = {
        "schemaVersion": "agent-review-mesh-operator-template-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "templateId": template_id if isinstance(template_id, str) else None,
        "blockers": blockers,
        "templateDigest": template.get("templateDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_review_mesh_operator_template_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "review-mesh-template-validation-failed",
            "Review Mesh operator template validation failed",
            {"validation": validation},
        )
    return validation


def parse_reviewer_spec(spec: str) -> dict[str, str]:
    """Parse id[:role[:model-class]] into a provider-neutral reviewer descriptor."""

    parts = spec.split(":")
    if len(parts) > 3:
        raise LifecycleError("review-mesh-reviewer-spec-invalid", "reviewer spec must be id[:role[:model-class]]")
    reviewer_id = parts[0].strip() if parts else ""
    role = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "reviewer"
    model_class = parts[2].strip() if len(parts) > 2 and parts[2].strip() else "strong-reasoning"
    return _reviewer_from_mapping({"id": reviewer_id, "role": role, "modelClass": model_class})


def prepare_review_mesh_operator_packets(
    *,
    source: dict[str, Any],
    template_id: str,
    reviewers: list[dict[str, str]] | None = None,
    profile_id: str | None = None,
    phase: str | None = None,
    blocking: bool = False,
    evidence_ids: list[str] | None = None,
    out_dir: Path | None = None,
    review_input: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    authority_manifest: dict[str, Any] | None = None,
    summary_output: Path | None = None,
) -> dict[str, Any]:
    """Prepare local Review Mesh packets and an auditable receipt."""

    template = get_review_mesh_operator_template(template_id)
    require_review_mesh_operator_template_pass(validate_review_mesh_operator_template(template))
    selected_reviewers = reviewers or [_reviewer_from_mapping(item) for item in template["defaultReviewers"]]
    if len(selected_reviewers) < template["requiredReviewers"]:
        raise LifecycleError(
            "review-mesh-prepare-reviewer-count-insufficient",
            "template requires more reviewers",
            {"requiredReviewers": template["requiredReviewers"], "actualReviewers": len(selected_reviewers)},
        )
    if blocking and not _source_has_blocking_opt_in(source):
        raise LifecycleError(
            "review-mesh-prepare-blocking-without-plan-opt-in", "blocking Review Mesh requires a frozen plan opt-in"
        )
    selected_phase = phase or template["phase"]
    handoff = None
    if review_input is not None:
        if out_dir is None or repository_root is None or authority_manifest is None:
            raise LifecycleError(
                "review-handoff-context-required", "Bounded handoff requires manifest, root and output"
            )
        if len({item["id"] for item in selected_reviewers}) != len(selected_reviewers):
            raise LifecycleError("review-handoff-reviewer-duplicate", "Reviewer seats require distinct identifiers")
        repository_root = repository_root.resolve(strict=True)
        handoff = _prepare_review_handoff(review_input, source, selected_phase, authority_manifest, repository_root)
        source = {**source, "reviewHandoff": handoff}
    profile = build_review_mesh_profile(
        profile_id=profile_id or f"{template_id}-profile",
        modes=[template["mode"]],
        default_mode=template["mode"],
        budget_cap=dict(template["budgetCap"]),
        live_calls_allowed=False,
        independence_required=bool(template["independenceRequired"]),
        independence_dimensions=list(template["independenceDimensions"]),
        reviewer_model_classes=_unique_model_classes(selected_reviewers),
    )
    packets = [
        build_review_mesh_assignment_packet(
            source=source,
            mode=template["mode"],
            phase=selected_phase,
            assignment_id=f"{template_id}-{index}",
            reviewer_id=reviewer["id"],
            reviewer_role=reviewer["role"],
            reviewer_model_class=reviewer["modelClass"],
            blocking=blocking,
            profile=profile,
            evidence_ids=evidence_ids or [],
        )
        for index, reviewer in enumerate(selected_reviewers, start=1)
    ]
    if handoff is not None:
        _response_instructions(packets, profile, handoff["responseContract"])
        assert out_dir is not None and repository_root is not None and authority_manifest is not None
        artifacts = _write_handoff_artifacts(
            out_dir,
            repository_root,
            authority_manifest,
            profile,
            packets,
            handoff,
            summary_output,
        )
    else:
        artifacts = _write_prepare_artifacts(out_dir=out_dir, profile=profile, packets=packets) if out_dir else []
    body = {
        "schemaVersion": REVIEW_MESH_PREPARE_RECEIPT_SCHEMA,
        "status": "PASS",
        "template": _template_summary(template),
        "source": _source_summary(source),
        "profile": profile,
        "assignmentPackets": packets,
        "artifacts": artifacts,
        "reviewerCount": len(packets),
        "requiredReviewers": template["requiredReviewers"],
        "mode": template["mode"],
        "phase": selected_phase,
        "blocking": bool(blocking),
        "blockingRequiresPlanOptIn": True,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "promptAuthorityGranted": False,
        "portableContractStoresConcreteProviderModel": False,
        "productionPromotionClaimed": False,
        **(
            {
                "reviewHandoff": {
                    "subjectDigest": handoff["subjectDigest"],
                    "readingIndexPath": "reading-index.json",
                    "localCompleteness": True,
                    "remoteDeliveryObserved": False,
                }
            }
            if handoff is not None
            else {}
        ),
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _prepare_review_handoff(
    request: dict[str, Any],
    source: dict[str, Any],
    phase: str,
    manifest: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    allowed = {
        "schemaVersion",
        "sourceRevision",
        "phase",
        "scope",
        "inputs",
        "previousFindings",
        "reviewChain",
        "authorityRefs",
        "budgetRefs",
        "responseExtensions",
        "responseContract",
    }
    required = allowed.difference({"responseExtensions", "responseContract"})
    if (
        type(request) is not dict
        or set(request).difference(allowed)
        or not required.issubset(request)
        or request["schemaVersion"] != "agent-review-input-inventory.v1"
        or len(canonical_bytes(request)) > 65536
    ):
        raise LifecycleError("review-handoff-input-invalid", "Invalid bounded review inventory")
    revision = request["sourceRevision"]
    if (
        type(revision) is not str
        or len(revision) not in (40, 64)
        or any(character not in "0123456789abcdef" for character in revision)
        or request["sourceRevision"] != source.get("sourceRevision")
        or canonical_digest(manifest) != source.get("digest")
        or request["phase"] != phase
    ):
        raise LifecycleError("review-handoff-source-mismatch", "Review source, revision or phase differs")
    _, sensitive = redact_value(request)
    if sensitive:
        raise LifecycleError("review-handoff-sensitive-metadata", "Portable metadata contains sensitive content")
    scope = _review_scope(request["scope"], manifest, root)
    entries = _review_input_entries(request["inputs"], root, revision)
    by_id = {item["id"]: item for item in entries}
    _review_chain(request, by_id)
    if not set(scope["evidenceIds"]).issubset(by_id):
        raise LifecycleError("review-handoff-evidence-missing", "Required evidence IDs are absent")
    paths = {item["path"] for item in entries}
    if not set(scope["changedPaths"]).issubset(paths):
        raise LifecycleError("review-handoff-source-missing", "Required source paths are absent")
    contract = build_response_contract(
        request.get(
            "responseExtensions",
            {
                "coverage": {"type": "array", "paths": scope["changedPaths"]},
            },
        )
    )
    coverage = contract["extensions"].get("coverage")
    if coverage is not None and coverage["paths"] != scope["changedPaths"]:
        raise LifecycleError("review-response-coverage-invalid", "Coverage must bind the declared subject paths")
    if "responseContract" in request:
        requested = require_response_contract(request["responseContract"])
        if requested["contractDigest"] != contract["contractDigest"]:
            raise LifecycleError("review-response-contract-mismatch", "Requested and collector contracts differ")
    subject = {
        "source": _source_summary(source),
        "sourceRevision": request["sourceRevision"],
        "phase": phase,
        "scope": scope,
        "inputs": entries,
        "previousFindings": request["previousFindings"],
        "reviewChain": request["reviewChain"],
        "authorityRefs": request["authorityRefs"],
        "budgetRefs": request["budgetRefs"],
        "responseContractDigest": contract["contractDigest"],
    }
    digest = canonical_digest(subject)
    index = {
        "schemaVersion": "agent-review-reading-index.v1",
        "subject": subject,
        "subjectDigest": digest,
        "readChunkBytes": 8192,
        "localCompleteness": True,
        "remoteDeliveryObserved": False,
        "modelCallsStarted": False,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    if len(canonical_bytes(index)) > 65536:
        raise LifecycleError("review-handoff-index-too-large", "Index must be split before preparation")
    return {"subjectDigest": digest, "responseContract": contract, "index": index}


def _review_scope(value: Any, manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "kind",
        "taskIds",
        "changedPaths",
        "acceptanceIds",
        "evidenceIds",
    }:
        raise LifecycleError("review-handoff-scope-invalid", "Complete typed scope is required")
    tasks = _review_ids(value["taskIds"])
    selected = [item for item in manifest["workstreams"] if item["id"] in tasks]
    if not tasks or len(selected) != len(tasks):
        raise LifecycleError("review-handoff-scope-invalid", "Review task IDs differ from the manifest")
    for field in ("acceptanceIds", "evidenceIds"):
        expected = {entry for task in selected for entry in task.get(field, [])}
        if set(_review_ids(value[field])) != expected:
            raise LifecycleError("review-handoff-scope-mismatch", "Required acceptance or evidence differs")
    paths = [normalize_repo_path(name) for name in _review_ids(value["changedPaths"], allow_empty=True)]
    if value["kind"] == "PLAN_PACKAGE":
        pending = manifest.get("planReview", {}).get("report")
        expected = {name for name in manifest["planFiles"] if name != pending or (root / name).exists()}
    elif value["kind"] == "TASK_CHANGESET":
        writes = sorted({name for task in selected for name in task.get("writes", [])})
        captured = capture_task_change_set(root, baseline=manifest["baseRevision"]["sha"], write_paths=writes)
        expected = set(captured["changedFiles"])
    else:
        raise LifecycleError("review-handoff-scope-invalid", "Unsupported review scope kind")
    if set(paths) != expected:
        raise LifecycleError("review-handoff-scope-mismatch", "Complete current subject paths are required")
    return {**value, "changedPaths": sorted(paths)}


def _review_ids(value: Any, *, allow_empty: bool = False) -> list[str]:
    if (
        type(value) is not list
        or len(value) > 256
        or (not value and not allow_empty)
        or any(type(item) is not str or not item or len(item) > 4096 for item in value)
        or len(set(value)) != len(value)
    ):
        raise LifecycleError("review-handoff-identities-invalid", "Identities must be finite and unique")
    return value


def _review_input_entries(value: Any, root: Path, revision: str) -> list[dict[str, Any]]:
    if type(value) is not list or not 1 <= len(value) <= 64:
        raise LifecycleError("review-handoff-inventory-invalid", "Declare between 1 and 64 required inputs")
    entries = []
    total = 0
    raw_by_path = {}
    for item in value:
        if type(item) is not dict or set(item).difference({"id", "path", "bytes", "sha256", "ranges"}):
            raise LifecycleError("review-handoff-inventory-invalid", "Invalid required input")
        _review_ids([item.get("id")])
        path = normalize_repo_path(item.get("path", ""))
        if any(
            part.startswith(".env")
            or part
            in {
                ".git",
                ".alk",
                ".codex",
                ".claude",
                ".ssh",
                "credentials.json",
                "secrets.json",
                "id_rsa",
                "id_ed25519",
            }
            for part in Path(path).parts
        ):
            raise LifecycleError("review-handoff-private-input", "Host-private inputs cannot be indexed")
        raw = read_stable_repository_file(root, path, max_bytes=8_388_608)
        total += len(raw)
        if total > 8_388_608 or type(item.get("bytes")) is not int or item["bytes"] != len(raw):
            raise LifecycleError("review-handoff-size-mismatch", "Required input size or aggregate cap differs")
        if item.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise LifecycleError("review-handoff-stale-input", "Required input digest differs")
        ranges = _review_ranges(item.get("ranges", [{"start": 0, "end": len(raw)}]), raw)
        entries.append({"id": item["id"], "path": path, "bytes": len(raw), "sha256": item["sha256"], "ranges": ranges})
        raw_by_path[path] = raw
    _review_ids([item["id"] for item in entries])
    observed_authority_paths([item["path"] for item in entries], operation_root=root)
    if len(raw_by_path) != len(entries):
        raise LifecycleError("review-handoff-path-duplicate", "Required input paths must be unique")
    availability = _review_clone_availability(root, raw_by_path, revision)
    for item in entries:
        item["cloneAvailability"] = availability[item["path"]]
    return entries


def _review_ranges(value: Any, raw: bytes) -> list[dict[str, Any]]:
    if type(value) is not list or not 1 <= len(value) <= 64:
        raise LifecycleError("review-handoff-ranges-invalid", "Declare bounded byte ranges")
    result = []
    last = 0
    for item in value:
        if (
            type(item) is not dict
            or set(item) != {"start", "end"}
            or type(item["start"]) is not int
            or type(item["end"]) is not int
            or not last <= item["start"] <= item["end"] <= len(raw)
            or (item["start"] == item["end"] and raw)
        ):
            raise LifecycleError("review-handoff-ranges-invalid", "Ranges must be ordered and nonoverlapping")
        start, last = item["start"], item["end"]
        result.append(
            {
                **item,
                "sha256": hashlib.sha256(raw[start:last]).hexdigest(),
                "chunkCount": math.ceil((last - start) / 8192),
            }
        )
    return result


def _review_chain(request: dict[str, Any], inputs: dict[str, Any]) -> None:
    chain = request["reviewChain"]
    if (
        type(chain) is not list
        or len(chain) != 3
        or [item.get("stage") for item in chain if isinstance(item, dict)] != ["area", "integration", "final"]
    ):
        raise LifecycleError("review-handoff-chain-invalid", "Declare area, integration and final stages")
    for item in chain:
        if (
            set(item) != {"stage", "roleSlots", "remediationSlots"}
            or type(item["roleSlots"]) is not int
            or not 1 <= item["roleSlots"] <= 64
            or type(item["remediationSlots"]) is not int
            or not 0 <= item["remediationSlots"] <= 16
        ):
            raise LifecycleError("review-handoff-chain-invalid", "Review slots must be finite integers")
    for field in ("authorityRefs", "budgetRefs"):
        if not set(_review_ids(request[field])).issubset(inputs):
            raise LifecycleError("review-handoff-reference-missing", "Authority or budget reference is absent")
    findings = request["previousFindings"]
    if (
        type(findings) is not list
        or len(findings) > 128
        or any(type(item) is not dict or type(item.get("id")) is not str for item in findings)
    ):
        raise LifecycleError("review-handoff-findings-invalid", "Previous findings must be bounded typed data")
    _review_ids([item["id"] for item in findings], allow_empty=True)


def _review_clone_availability(root: Path, raw: dict[str, bytes], revision: str) -> dict[str, str]:
    # Index no content. A clone alone cannot reproduce local/uncommitted bytes.
    result = {name: "UNAVAILABLE_REQUIRES_LOCAL_INPUT" for name in raw}
    command = run_bounded_command(
        ["git", "--literal-pathspecs", "ls-tree", "-z", "--full-tree", revision, "--", *raw],
        cwd=root,
        timeout_seconds=5,
        max_stdout_bytes=524288,
        max_stderr_bytes=8192,
    )
    if command.returncode:
        return result
    blobs = {}
    for entry in command.stdout.split(b"\0"):
        if entry:
            meta, raw_name = entry.split(b"\t", 1)
            _mode, kind, blob_oid = meta.decode().split()
            if kind == "blob":
                blobs[raw_name.decode("utf-8")] = blob_oid
    for name, data in raw.items():
        oid = blobs.get(name)
        if oid is None:
            result[name] = "LOCAL_ONLY"
        else:
            algorithm = "sha1" if len(oid) == 40 else "sha256"
            digest = hashlib.new(
                algorithm,
                b"blob " + str(len(data)).encode() + b"\0" + data,
                usedforsecurity=False,
            ).hexdigest()
            result[name] = "SOURCE_REVISION_MATCH" if digest == oid else "LOCAL_CHANGES_REQUIRED"
    return result


def _response_instructions(packets: list[dict[str, Any]], profile: dict[str, Any], contract: dict[str, Any]) -> None:
    for packet in packets:
        assignment = packet["assignment"]
        example = {
            "schemaVersion": contract["rawSchemaVersion"],
            "status": "SKIPPED",
            "findings": [],
            "contractDigest": contract["contractDigest"],
            "subjectDigest": assignment["subject"]["subjectDigest"],
            "assignmentDigest": assignment["assignmentDigest"],
        }
        if "coverage" in contract["extensions"]:
            example["coverage"] = contract["extensions"]["coverage"]["paths"]
        import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=example)
        packet["reviewerTask"].update(
            expectedResultSchema=contract["rawSchemaVersion"],
            responseFormat={
                "contract": contract,
                "example": example,
                "exampleIsCompletion": False,
                "instructions": "Read every indexed required range; report incomplete coverage when inaccessible. "
                "Return actual findings and unknown usage as null. This example is format only.",
            },
        )
        packet["packetDigest"] = canonical_digest(
            {key: value for key, value in packet.items() if key != "packetDigest"}
        )
        if len(canonical_bytes(packet)) > 98304:
            raise LifecycleError("review-handoff-packet-too-large", "Prepared packet exceeds its context cap")


def _write_handoff_artifacts(
    directory: Path,
    root: Path,
    manifest: dict[str, Any],
    profile: dict[str, Any],
    packets: list[dict[str, Any]],
    handoff: dict[str, Any],
    summary: Path | None,
) -> list[dict[str, Any]]:
    directory = directory if directory.is_absolute() else root / directory
    base = repository_authority_name(directory, root)
    values = {base + "/profile.json": profile, base + "/reading-index.json": handoff["index"]}
    values.update({base + "/assignments/" + p["assignment"]["assignmentId"] + ".json": p for p in packets})
    names = [base, base + ".reservation.json", *values]
    if summary is not None:
        summary = summary if summary.is_absolute() else root / summary
        names.append(repository_authority_name(summary, root))
    require_output_footprint(manifest, names, repository_root=root)
    for forbidden in manifest.get("forbiddenWrites", []):
        if any(is_under_authority_path(name, forbidden, operation_root=root) for name in names):
            raise LifecycleError("review-handoff-output-conflict", "Output is inside a forbidden write path")
    if len(set(names)) != len(names) or any((root / name).exists() for name in names):
        raise LifecycleError("review-handoff-output-exists", "Handoff output must be entirely new")
    for entry in handoff["index"]["subject"]["inputs"]:
        path = root / entry["path"]
        data = read_stable_repository_file(root, entry["path"], max_bytes=8_388_608)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise LifecycleError("review-handoff-stale-input", "Required input changed before writing")
        if directory == path or directory in path.parents:
            raise LifecycleError("review-handoff-output-conflict", "Output overlaps required inputs")
    create_authority_bytes(
        root / (base + ".reservation.json"),
        canonical_bytes(
            {
                "subjectDigest": handoff["subjectDigest"],
                "authorityClaimed": False,
            }
        )
        + b"\n",
        root=root,
    )
    artifacts = []
    for name, value in values.items():
        create_authority_bytes(root / name, canonical_bytes(value) + b"\n", root=root)
        artifacts.append(
            {
                "role": "reading-index"
                if name.endswith("reading-index.json")
                else "profile"
                if name.endswith("profile.json")
                else "assignment-packet",
                "path": name[len(base) + 1 :],
                "digest": canonical_digest(value),
            }
        )
    return artifacts


def iter_reading_ranges(root: Path, index: dict[str, Any]):
    """Retrieve all declared bytes in bounded chunks, including long JSON lines."""
    subject = index.get("subject")
    if (
        index.get("schemaVersion") != "agent-review-reading-index.v1"
        or not isinstance(subject, dict)
        or type(subject.get("inputs")) is not list
        or not 1 <= len(subject["inputs"]) <= 64
        or canonical_digest(subject) != index.get("subjectDigest")
        or index.get("readChunkBytes") != 8192
    ):
        raise LifecycleError("review-handoff-index-invalid", "Reading index identity differs")
    total = 0
    for entry in subject["inputs"]:
        data = read_stable_repository_file(root, entry["path"], max_bytes=8_388_608)
        total += len(data)
        if total > 8_388_608:
            raise LifecycleError("review-handoff-index-invalid", "Reading inventory exceeds its byte cap")
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise LifecycleError("review-handoff-stale-input", "Required material is missing or stale")
        ranges = _review_ranges(
            [{"start": selected["start"], "end": selected["end"]} for selected in entry["ranges"]], data
        )
        if canonical_digest(ranges) != canonical_digest(entry["ranges"]):
            raise LifecycleError("review-handoff-index-invalid", "Selected range metadata differs")
        for selected in ranges:
            content = data[selected["start"] : selected["end"]]
            if hashlib.sha256(content).hexdigest() != selected["sha256"]:
                raise LifecycleError("review-handoff-index-invalid", "Selected byte range differs")
            for offset in range(0, len(content), 8192):
                yield entry["id"], selected["start"] + offset, content[offset : offset + 8192]


def _write_prepare_artifacts(
    *, out_dir: Path, profile: dict[str, Any], packets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    profile_path = out_dir / "profile.json"
    write_json_create(profile_path, profile)
    artifacts.append({"role": "profile", "path": "profile.json", "digest": profile["profileDigest"]})
    assignments_dir = out_dir / "assignments"
    assignments_dir.mkdir(parents=True, exist_ok=True)
    for packet in packets:
        assignment_id = packet["assignment"]["assignmentId"]
        relative_path = f"assignments/{assignment_id}.json"
        write_json_create(assignments_dir / f"{assignment_id}.json", packet)
        artifacts.append({"role": "assignment-packet", "path": relative_path, "digest": packet["packetDigest"]})
    return artifacts


def _reviewer_from_mapping(value: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise LifecycleError("review-mesh-reviewer-invalid", "reviewer must be an object")
    reviewer_id = _required_string(value.get("id"), "review-mesh-reviewer-id-invalid")
    role = _required_string(value.get("role"), "review-mesh-reviewer-role-invalid")
    model_class = _required_string(value.get("modelClass"), "review-mesh-reviewer-model-class-invalid")
    if model_class not in ALLOWED_MODEL_CLASSES or model_class == "no-model":
        raise LifecycleError(
            "review-mesh-reviewer-model-class-invalid",
            "reviewer model class is not allowed",
            {"modelClass": model_class},
        )
    return {"id": reviewer_id, "role": role, "modelClass": model_class}


def _unique_model_classes(reviewers: list[dict[str, str]]) -> list[str]:
    return sorted({reviewer["modelClass"] for reviewer in reviewers})


def _source_has_blocking_opt_in(source: dict[str, Any]) -> bool:
    review_mesh = source.get("reviewMesh")
    return isinstance(review_mesh, dict) and review_mesh.get("required") is True


def _source_summary(source: dict[str, Any]) -> dict[str, Any]:
    digest = source.get("digest")
    return {
        "kind": source.get("kind"),
        "label": source.get("label"),
        "digest": digest if isinstance(digest, str) else canonical_digest(source),
        "status": source.get("status"),
        "reviewMeshRequired": _source_has_blocking_opt_in(source),
    }


def _template_summary(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "templateId": template["templateId"],
        "mode": template["mode"],
        "phase": template["phase"],
        "templateDigest": template["templateDigest"],
    }


def _required_string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, "required string is missing")
    return value
