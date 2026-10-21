"""Validate independent review envelopes."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.authority_text import require_manifest_text, require_review_text
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.plan_delta_schemas import (
    COMPOSITE_REVIEW_SCHEMA,
    IMPACT_SELECTION_SCHEMA,
    MAX_IMPACT_EDGES,
    MAX_IMPACT_NODES,
    MAX_REVIEW_CHAIN_BYTES,
    MAX_REVIEW_DEPENDENCY_EDGES,
    MAX_REVIEW_REPORTS,
    PLAN_IMPACT_GRAPH_SCHEMA,
    REVIEW_SCOPE_SCHEMA,
)
from agent_lifecycle.contracts.review_verdict import open_blocking_finding_ids
from agent_lifecycle.contracts.reviewer_identity_schemas import parse_reviewer_utc
from agent_lifecycle.review.provenance import validate_native_reviewer_provenance


def require_supported_review_provenance(review: dict[str, Any], *, native_phase: str) -> None:
    """Keep ordinary declarations; refuse caller-supplied native authority."""
    candidates = [review]
    if "auditor" in review:
        candidates.append({**review, "reviewer": review["auditor"]})
    for candidate in candidates:
        validation = validate_native_reviewer_provenance(candidate, native_phase=native_phase)
        if validation["status"] == "FAIL" or ("reviewerProvenance" in review and review["reviewerProvenance"] is None):
            raise LifecycleError(
                "review-provenance-invalid",
                "review provenance claim is malformed or unverified",
                {"validation": validation},
            )
    supplied = review.get("reviewerProvenance")
    if isinstance(supplied, dict) and supplied.get("guarantee") == "ATTESTED":
        raise LifecycleError(
            "review-provenance-unsupported",
            "native ATTESTED reviewer provenance is unavailable",
            {"validation": validation},
        )


def validate_independent_review(review: dict[str, Any]) -> dict[str, Any]:
    require_review_text(review)
    require_supported_review_provenance(review, native_phase="freeze")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("independent") is not True:
        raise LifecycleError("review-not-independent", "reviewer must be independent")
    verdict = review.get("verdict")
    if verdict not in {"READY_TO_FREEZE", "ACCEPTED", "CHANGES_REQUIRED", "BLOCKED"}:
        raise LifecycleError("invalid-review", "review verdict is invalid")
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        raise LifecycleError("invalid-review", "findings must be an array")
    open_blocking = open_blocking_finding_ids(findings)
    if verdict in {"READY_TO_FREEZE", "ACCEPTED"} and open_blocking:
        raise LifecycleError("review-open-findings", "review has unresolved blocking findings")
    return {"schemaVersion": "agent-review-validation.v1", "verdict": verdict, "openBlocking": open_blocking}


def build_review_impact_graph(
    manifest: dict[str, Any],
    *,
    file_digests: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Derive review dependencies from the complete manifest, not caller edges.

    This pure review-domain projection is shared by planning, audit and freeze.
    It deliberately overselects connected surfaces instead of hiding ambiguity.
    File bodies stay outside the graph; immutable digests bind their coverage.
    """
    if not isinstance(manifest, dict):
        raise LifecycleError("review-impact-input-invalid", "Expected manifest")
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str]] = set()
    specification = _impact_object(manifest.get("specification"))
    requirements = _impact_items(specification.get("requirements"), "requirement")
    criteria = _impact_items(_impact_object(manifest.get("acceptance")).get("criteria"), "acceptance")
    workstreams = _impact_items(manifest.get("workstreams"), "workstream")
    _impact_add_items(nodes, requirements, "requirement")
    _impact_add_items(nodes, criteria, "acceptance")
    _impact_add_items(nodes, workstreams, "workstream")
    evidence = _impact_evidence(criteria, workstreams)
    for item in evidence:
        _impact_add(nodes, "evidence:" + item, "evidence", {"id": item})
    _impact_links(nodes, edges, requirements, criteria, workstreams)
    _impact_paths(nodes, edges, workstreams)
    _impact_controls(nodes, edges, manifest, workstreams)
    _impact_files(nodes, edges, manifest, file_digests)
    _impact_add(
        nodes,
        "budget",
        "budget",
        {key: manifest.get(key) for key in ("budgetPolicy", "orchestration", "contextLimits")},
    )
    _impact_add(
        nodes,
        "specification",
        "specification",
        {key: value for key, value in specification.items() if key != "requirements"},
    )
    _impact_add(
        nodes,
        "acceptance-policy",
        "acceptance",
        {key: value for key, value in manifest["acceptance"].items() if key != "criteria"},
    )
    represented = {
        "specification",
        "acceptance",
        "workstreams",
        "securityGates",
        "finalAuditGates",
        "budgetPolicy",
        "orchestration",
        "contextLimits",
        "readOnly",
        "forbiddenWrites",
        "leadOwned",
        "planFiles",
    }
    _impact_add(
        nodes, "metadata", "metadata", {key: value for key, value in manifest.items() if key not in represented}
    )
    for task_id in workstreams:
        for control in ("budget", "specification", "acceptance-policy"):
            _impact_edge(nodes, edges, control, "workstream:" + task_id)
    return _impact_result(manifest, nodes, edges)


def review_impact_closure(graphs: list[dict[str, Any]], changed: list[str]) -> list[str]:
    """Walk outgoing impact dependencies from both before/after graphs.

    Removed edges/nodes still affect the old dependants. Cycles are harmless
    in this bounded impact graph; review-report provenance has separate limits.
    """
    neighbours: dict[str, set[str]] = {}
    for graph in graphs:
        for node in graph["nodes"]:
            neighbours.setdefault(node["id"], set())
        for edge in graph["edges"]:
            left, right = edge["from"], edge["to"]
            neighbours[left].add(right)
    if not set(changed) <= set(neighbours):
        raise LifecycleError("review-impact-unknown-node", "Unknown impact")
    pending = list(changed)
    visited: set[str] = set()
    while pending:
        node = pending.pop()
        if node not in visited:
            visited.add(node)
            pending.extend(neighbours[node] - visited)
    return sorted(visited)


def _impact_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("review-impact-incomplete", "Object is missing")
    return value


def _impact_items(value: Any, kind: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise LifecycleError("review-impact-incomplete", "Missing " + kind)
    result = {}
    for item in value:
        if not isinstance(item, dict):
            raise LifecycleError("review-impact-invalid", "Invalid " + kind)
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 160 or identifier in result:
            raise LifecycleError("review-impact-invalid", "Duplicate/invalid id")
        result[identifier] = item
    return result


def _impact_add(nodes: dict[str, dict[str, Any]], key: str, kind: str, payload: Any) -> None:
    if key in nodes:
        raise LifecycleError("review-impact-invalid", "Duplicate graph node")
    nodes[key] = {
        "id": key,
        "kind": kind,
        "payload": payload,
        "digest": canonical_digest(payload),
    }
    if len(nodes) > MAX_IMPACT_NODES:
        raise LifecycleError("review-impact-limit", "Impact graph is too large")


def _impact_add_items(
    nodes: dict[str, dict[str, Any]],
    items: dict[str, dict[str, Any]],
    kind: str,
) -> None:
    for identifier, item in items.items():
        _impact_add(nodes, kind + ":" + identifier, kind, item)


def _impact_edge(
    nodes: dict[str, dict[str, Any]],
    edges: set[tuple[str, str]],
    left: str,
    right: str,
) -> None:
    if left not in nodes or right not in nodes:
        raise LifecycleError("review-impact-incomplete", "Unresolved edge")
    edges.add((left, right))
    if len(edges) > MAX_IMPACT_EDGES:
        raise LifecycleError("review-impact-limit", "Too many impact edges")


def _impact_evidence(
    criteria: dict[str, dict[str, Any]],
    workstreams: dict[str, dict[str, Any]],
) -> list[str]:
    result = set()
    for item in [*criteria.values(), *workstreams.values()]:
        result.update(_impact_refs(item, "evidenceIds"))
    return sorted(result)


def _impact_refs(item: dict[str, Any], key: str) -> list[str]:
    value = item.get(key, [])
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise LifecycleError("review-impact-invalid", "Invalid " + key)
    if len(set(value)) != len(value):
        raise LifecycleError("review-impact-invalid", "Duplicate " + key)
    return value


def _impact_links(
    nodes: dict[str, dict[str, Any]],
    edges: set[tuple[str, str]],
    requirements: dict[str, dict[str, Any]],
    criteria: dict[str, dict[str, Any]],
    workstreams: dict[str, dict[str, Any]],
) -> None:
    for identifier, criterion in criteria.items():
        key = "acceptance:" + identifier
        required = _impact_refs(criterion, "requirementIds")
        if not required or not _impact_refs(criterion, "evidenceIds"):
            raise LifecycleError("review-impact-incomplete", "Unlinked criterion")
        for requirement in required:
            _impact_edge(nodes, edges, "requirement:" + requirement, key)
        for evidence in _impact_refs(criterion, "evidenceIds"):
            _impact_edge(nodes, edges, "evidence:" + evidence, key)
    for identifier, task in workstreams.items():
        key = "workstream:" + identifier
        if not _impact_refs(task, "acceptanceIds"):
            raise LifecycleError("review-impact-incomplete", "Unlinked task")
        for criterion_id in _impact_refs(task, "acceptanceIds"):
            _impact_edge(nodes, edges, "acceptance:" + criterion_id, key)
        for evidence in _impact_refs(task, "evidenceIds"):
            _impact_edge(nodes, edges, "evidence:" + evidence, key)
        for dependency in _impact_refs(task, "dependsOn"):
            _impact_edge(nodes, edges, "workstream:" + dependency, key)
    linked = {x for edge in edges for x in edge}
    if any("requirement:" + key not in linked for key in requirements):
        raise LifecycleError("review-impact-incomplete", "Uncovered requirement")


def _impact_paths(
    nodes: dict[str, dict[str, Any]],
    edges: set[tuple[str, str]],
    workstreams: dict[str, dict[str, Any]],
) -> None:
    for identifier, task in workstreams.items():
        for path in _impact_refs(task, "writes"):
            key = "path:" + path
            if key not in nodes:
                _impact_add(nodes, key, "path", {"path": path})
            owner = "ownership:" + identifier + ":" + path
            _impact_add(
                nodes,
                owner,
                "ownership",
                {
                    "path": path,
                    "owner": task.get("owner"),
                    "task": identifier,
                },
            )
            _impact_edge(nodes, edges, owner, key)
            _impact_edge(nodes, edges, "workstream:" + identifier, owner)


def _impact_controls(
    nodes: dict[str, dict[str, Any]],
    edges: set[tuple[str, str]],
    manifest: dict[str, Any],
    workstreams: dict[str, dict[str, Any]],
) -> None:
    for kind, name in (("security", "securityGates"), ("final", "finalAuditGates")):
        values = manifest.get(name, [])
        if not isinstance(values, list):
            raise LifecycleError("review-impact-invalid", "Invalid gates")
        for index, gate in enumerate(values):
            identifier = gate.get("id") if isinstance(gate, dict) else gate
            identifier = str(identifier or index)
            key = kind + ":" + identifier
            _impact_add(nodes, key, kind, gate)
            for task in workstreams:
                if kind == "security":
                    _impact_edge(nodes, edges, key, "workstream:" + task)
                else:
                    _impact_edge(nodes, edges, "workstream:" + task, key)
    _impact_add(
        nodes,
        "ownership",
        "ownership",
        {key: manifest.get(key, []) for key in ("readOnly", "forbiddenWrites", "leadOwned")},
    )
    for task in workstreams:
        _impact_edge(nodes, edges, "ownership", "workstream:" + task)


def _impact_files(
    nodes: dict[str, dict[str, Any]],
    edges: set[tuple[str, str]],
    manifest: dict[str, Any],
    file_digests: dict[str, str] | None,
) -> None:
    files = manifest.get("planFiles", [])
    if not isinstance(files, list) or any(not isinstance(x, str) for x in files):
        raise LifecycleError("review-impact-invalid", "Invalid plan inventory")
    digests = {} if file_digests is None else file_digests
    if not isinstance(digests, dict):
        raise LifecycleError("review-impact-invalid", "Invalid file digests")
    outputs = review_output_paths(manifest)
    prefix = str(_impact_object(manifest.get("package")).get("planArtifactRoot")) + "/"
    for path in files:
        if path in outputs:
            continue
        relative = path[len(prefix) :] if path.startswith(prefix) else path
        key = "file:" + relative
        _impact_add(
            nodes,
            key,
            "file",
            {
                "relativePath": relative,
                "sha256": digests.get(path),
            },
        )
        # The manifest is fully projected above; its raw hash changes with the
        # revision/envelope even when semantic review inputs stay unchanged.
        if relative == "plan.manifest.json":
            continue
        for task in manifest["workstreams"]:
            _impact_edge(nodes, edges, key, "workstream:" + task["id"])


def _impact_result(
    manifest: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    edges: set[tuple[str, str]],
) -> dict[str, Any]:
    body = {
        "schemaVersion": PLAN_IMPACT_GRAPH_SCHEMA,
        "manifestHash": canonical_digest(manifest),
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [{"from": left, "to": right} for left, right in sorted(edges)],
    }
    return {**body, "graphDigest": canonical_digest(body)}


def review_output_paths(manifest: dict[str, Any]) -> set[str]:
    """Future reviews are outputs, not circular hashes of their own input."""
    review = manifest.get("planReview", {})
    paths = {review["report"]} if isinstance(review, dict) and isinstance(review.get("report"), str) else set()
    extensions = _impact_object(manifest.get("extensions", {}))
    policy = extensions.get("reviewPolicy", {})
    if isinstance(policy, dict):
        seats = policy.get("requiredSeats", [])
        if not isinstance(seats, list):
            raise LifecycleError("review-policy-invalid", "Invalid seats")
        for seat in seats:
            if isinstance(seat, dict):
                paths.update(_impact_refs(seat, "reports"))
    return paths


def make_review_subject(
    manifest: dict[str, Any],
    file_digests: dict[str, str],
    runtime_inputs: dict[str, str],
) -> dict[str, Any]:
    """Capture explicit review inputs; this data grants no review authority."""
    manifest = _impact_object(manifest)
    require_manifest_text(manifest)
    if manifest.get("schemaVersion") != "agent-plan.v1":
        raise LifecycleError("review-subject-unsupported", "Unsupported manifest schema")
    status = manifest.get("status")
    if not isinstance(status, str) or status not in {"DRAFT", "FROZEN"}:
        raise LifecycleError("review-subject-unsupported", "Unsupported manifest status")
    package = _impact_object(manifest.get("package"))
    if not isinstance(package.get("id"), str) or not package["id"]:
        raise LifecycleError("review-input-invalid", "Missing package identity")
    revision = manifest.get("planRevision")
    if type(revision) is not int or revision < 1:
        raise LifecycleError("review-input-invalid", "Invalid plan revision")
    source = _impact_object(manifest.get("baseRevision")).get("sha")
    if not isinstance(source, str) or len(source) not in {40, 64}:
        raise LifecycleError("review-input-invalid", "Exact source identity needed")
    if any(char not in "0123456789abcdef" for char in source):
        raise LifecycleError("review-input-invalid", "Invalid source identity")
    root = package.get("planArtifactRoot")
    if not isinstance(root, str) or normalize_repo_path(root, label="plan artifact root") != root:
        raise LifecycleError("review-input-invalid", "Canonical package root needed")
    files = _impact_refs(manifest, "planFiles")
    if not isinstance(file_digests, dict) or not isinstance(runtime_inputs, dict):
        raise LifecycleError("review-input-invalid", "Expected input maps")
    expected = set(files) - review_output_paths(manifest)
    if not expected or set(file_digests) != expected or not runtime_inputs:
        raise LifecycleError("review-input-incomplete", "Unbound review inputs")
    for inventory in (file_digests, runtime_inputs):
        if len(inventory) > MAX_IMPACT_NODES:
            raise LifecycleError("review-input-limit", "Too many input files")
        if not isinstance(inventory, dict) or any(
            not isinstance(path, str) or not path or not _review_digest(digest) for path, digest in inventory.items()
        ):
            raise LifecycleError("review-input-invalid", "Invalid input hashes")
        for path in inventory:
            if normalize_repo_path(path, label="review input") != path:
                raise LifecycleError("review-input-invalid", "Noncanonical path")
    return {
        "manifest": manifest,
        "fileDigests": file_digests,
        "runtimeInputs": runtime_inputs,
    }


def make_review_scope(
    subject: dict[str, Any],
    *,
    kind: str = "FULL",
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render bound scope for an actual independent reviewer to decide upon."""
    subject = _checked_review_subject(subject)
    graph = build_review_impact_graph(subject["manifest"], file_digests=subject["fileDigests"])
    if kind not in {"FULL", "DELTA"}:
        raise LifecycleError("review-scope-invalid", "Unsupported review kind")
    if kind == "DELTA" and (
        not isinstance(selection, dict)
        or selection.get("mode") != "DELTA_ELIGIBLE"
        or selection.get("candidateHash") != graph["manifestHash"]
    ):
        raise LifecycleError("review-scope-invalid", "No eligible selection")
    body = {
        "schemaVersion": REVIEW_SCOPE_SCHEMA,
        "kind": kind,
        "candidateHash": graph["manifestHash"],
        "graphDigest": graph["graphDigest"],
        "fileInventoryDigest": canonical_digest(subject["fileDigests"]),
        "runtimeInputsDigest": canonical_digest(subject["runtimeInputs"]),
        "coveredNodes": [node["id"] for node in graph["nodes"]],
    }
    if kind == "DELTA":
        assert selection is not None
        body.update(
            {
                "baseHash": selection["baseHash"],
                "selectionDigest": selection["selectionDigest"],
                "coveredNodes": list(selection["closure"]),
            }
        )
    return body


def validate_bound_plan_review(review: dict[str, Any]) -> dict[str, Any]:
    """Validate complete input/scope bindings without promoting the verdict."""
    verdict = review.get("verdict")
    if not isinstance(verdict, str) or verdict not in {"READY_TO_FREEZE", "ACCEPTED", "CHANGES_REQUIRED"}:
        raise LifecycleError("review-baseline-verdict-unavailable", "No complete review verdict")
    validate_independent_review(review)
    _validate_review_identity_and_findings(review)
    if review.get("schemaVersion") != "agent-plan-review.v2":
        raise LifecycleError("review-scope-unavailable", "Bound v2 review needed")
    subject = _checked_review_subject(review.get("subject"))
    manifest = subject["manifest"]
    author = manifest.get("author")
    author_id = author.get("id") if isinstance(author, dict) else author
    if review["reviewer"]["id"] == author_id:
        raise LifecycleError("review-not-independent", "Author cannot review")
    if (
        review.get("reviewedPlanHash") != canonical_digest(manifest)
        or review.get("planRevision") != manifest.get("planRevision")
        or review.get("packageId") != manifest.get("package", {}).get("id")
    ):
        raise LifecycleError("review-subject-mismatch", "Wrong reviewed subject")
    scope = review.get("reviewScope")
    if not isinstance(scope, dict) or scope.get("kind") not in {"FULL", "DELTA"}:
        raise LifecycleError("review-scope-invalid", "Unsupported scope")
    expected = make_review_scope(subject)
    for key, value in expected.items():
        if key not in {"kind", "coveredNodes"} and scope.get(key) != value:
            raise LifecycleError("review-scope-mismatch", "Wrong " + key)
    nodes = scope.get("coveredNodes")
    if not isinstance(nodes, list) or any(not isinstance(x, str) for x in nodes):
        raise LifecycleError("review-scope-invalid", "Invalid covered nodes")
    if sorted(set(nodes)) != nodes:
        raise LifecycleError("review-scope-invalid", "Noncanonical coverage")
    if scope["kind"] == "FULL":
        if review.get("fullReview") is not True or nodes != expected["coveredNodes"]:
            raise LifecycleError("review-incomplete", "Complete baseline required")
    elif review.get("fullReview") is not False:
        raise LifecycleError("review-partial-as-full", "A delta is not full")
    return {"subject": subject, "scope": scope}


def derive_delta_selection(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Conservatively select impact, independently of any claimed approval."""
    before = _checked_review_subject(before)
    after = _checked_review_subject(after)
    left, right = before["manifest"], after["manifest"]
    graphs = [build_review_impact_graph(x["manifest"], file_digests=x["fileDigests"]) for x in (before, after)]
    nodes = [{x["id"]: x for x in graph["nodes"]} for graph in graphs]
    changed = {key for key in set(nodes[0]) | set(nodes[1]) if nodes[0].get(key) != nodes[1].get(key)}
    edge_sets = [{(x["from"], x["to"]) for x in g["edges"]} for g in graphs]
    for edge in edge_sets[0] ^ edge_sets[1]:
        changed.update(edge)
    for graph in graphs:
        final_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "final"}
        changed.update(e["from"] for e in graph["edges"] if e["to"] in changed & final_ids)
    reasons = _delta_refusal_reasons(before, after)
    removed = set(nodes[0]) - set(nodes[1])
    if any(nodes[0][key]["kind"] not in {"file", "metadata"} for key in removed):
        reasons.add("REMOVED_REVIEW_SURFACE")
    body = {
        "schemaVersion": IMPACT_SELECTION_SCHEMA,
        "mode": "FULL_REQUIRED" if reasons else "DELTA_ELIGIBLE",
        "reasons": sorted(reasons),
        "baseHash": canonical_digest(left),
        "candidateHash": canonical_digest(right),
        "baseGraphDigest": graphs[0]["graphDigest"],
        "graphDigest": graphs[1]["graphDigest"],
        "changedNodes": sorted(changed),
        "closure": review_impact_closure(graphs, sorted(changed)),
        "readOnly": True,
    }
    return {**body, "selectionDigest": canonical_digest(body)}


def _checked_review_subject(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"manifest", "fileDigests", "runtimeInputs"}:
        raise LifecycleError("review-input-incomplete", "Review subject missing")
    return make_review_subject(value["manifest"], value["fileDigests"], value["runtimeInputs"])


def _review_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _delta_refusal_reasons(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    left, right = before["manifest"], after["manifest"]
    reasons = set()
    if left.get("package", {}).get("id") != right.get("package", {}).get("id"):
        reasons.add("PACKAGE_MISMATCH")
    old_revision, revision = left.get("planRevision"), right.get("planRevision")
    if type(old_revision) is not int or type(revision) is not int or revision <= old_revision:
        reasons.add("NOT_A_SUCCESSOR")
    if left.get("baseRevision") != right.get("baseRevision") or before["runtimeInputs"] != after["runtimeInputs"]:
        reasons.add("RUNTIME_INPUTS_CHANGED")
    if _review_security_inputs(left) != _review_security_inputs(right):
        reasons.add("SECURITY_INPUTS_CHANGED")
    for key in ("author", "dependsOn", "releaseTarget", "packageIntegrity"):
        if left.get(key) != right.get(key):
            reasons.add("REVIEW_AUTHORITY_INPUTS_CHANGED")
    for key in (set(left.get("package", {})) | set(right.get("package", {}))) - {"planArtifactRoot", "title"}:
        if left.get("package", {}).get(key) != right.get("package", {}).get(key):
            reasons.add("PACKAGE_IDENTITY_CHANGED")
    known = {
        "schemaVersion",
        "status",
        "planRevision",
        "package",
        "planFiles",
        "packageIntegrity",
        "author",
        "baseRevision",
        "dependsOn",
        "releaseTarget",
        "developerOverview",
        "specification",
        "planReview",
        "implementationAudit",
        "readOnly",
        "forbiddenWrites",
        "leadOwned",
        "workstreams",
        "acceptance",
        "validation",
        "orchestration",
        "securityGates",
        "budgetPolicy",
        "contextLimits",
        "finalAuditGates",
        "extensions",
    }
    if any(left.get(key) != right.get(key) for key in (set(left) | set(right)) - known):
        reasons.add("UNKNOWN_IMPACT")
    return reasons


def _review_security_inputs(manifest: dict[str, Any]) -> dict[str, Any]:
    spec = _impact_object(manifest.get("specification", {}))
    extensions = dict(_impact_object(manifest.get("extensions", {})))
    policy = extensions.pop("reviewPolicy", {})
    if isinstance(policy, dict):
        seats = policy.get("requiredSeats", [])
        if not isinstance(seats, list) or any(not isinstance(s, dict) for s in seats):
            raise LifecycleError("review-policy-invalid", "Invalid seats")
        policy = {
            **policy,
            "requiredSeats": [
                {key: value for key, value in seat.items() if key not in {"reports", "baseline", "current"}}
                for seat in seats
            ],
        }
    return {
        "tier": spec.get("tier"),
        "risk": spec.get("tierResolutionRequest"),
        "securityGates": manifest.get("securityGates", []),
        "extensions": extensions,
        "reviewPolicy": policy,
        "implementationAudit": manifest.get("implementationAudit"),
        "validation": manifest.get("validation"),
    }


def _validate_review_identity_and_findings(review: dict[str, Any]) -> None:
    reviewer = _impact_object(review.get("reviewer"))
    for value in [review.get("reviewId"), *[reviewer.get(key) for key in ("id", "runId", "surface")]]:
        if not isinstance(value, str) or not value or len(value) > 160:
            raise LifecycleError("review-identity-invalid", "Missing identity")
    if reviewer.get("role") in {"coordinator", "assembler", "author"}:
        raise LifecycleError("review-not-independent", "Not a reviewer voice")
    seen = set()
    if not isinstance(review.get("findings"), list):
        raise LifecycleError("review-finding-invalid", "Findings required")
    if len(review["findings"]) > 128:
        raise LifecycleError("review-finding-invalid", "Too many findings")
    for finding in review["findings"]:
        if not isinstance(finding, dict):
            raise LifecycleError("review-finding-invalid", "Invalid finding")
        identifier = finding.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise LifecycleError("review-finding-invalid", "Invalid finding id")
        seen.add(identifier)
        if finding.get("severity") not in {"BLOCKER", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"} or finding.get(
            "status"
        ) not in {"OPEN", "CLOSED"}:
            raise LifecycleError("review-finding-invalid", "Unknown finding state")
        if finding.get("category") in {"INCOMPLETE_REVIEW", "NO_VERDICT"}:
            raise LifecycleError("review-incomplete", "Incomplete review")
    authority = _impact_object(review.get("reviewAuthority"))
    expected = {
        "reviewId": review["reviewId"],
        "reviewerId": reviewer["id"],
        "runId": reviewer["runId"],
        "subjectHash": review.get("reviewedPlanHash"),
        "status": "VALID",
    }
    if any(authority.get(key) != value for key, value in expected.items()):
        raise LifecycleError("review-authority-invalid", "Unbound call validity")
    start, end, completed = [
        parse_reviewer_utc(authority.get(key)) for key in ("notBefore", "expiresAt", "completedAt")
    ]
    if not start <= completed <= end:
        raise LifecycleError("review-authority-expired", "Call outside authority")
    _review_evidence(authority.get("evidence"))


def _review_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise LifecycleError("review-evidence-invalid", "Bound evidence needed")
    seen = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str)
            or not item["path"]
            or item["path"] in seen
            or not _review_digest(item["sha256"])
        ):
            raise LifecycleError("review-evidence-invalid", "Invalid evidence")
        seen.add(item["path"])
        if normalize_repo_path(item["path"], label="review evidence") != item["path"]:
            raise LifecycleError("review-evidence-invalid", "Noncanonical path")
    return value


def review_policy(manifest: dict[str, Any]) -> dict[str, Any]:
    """Read required voices from governing input, never from the assembler."""
    policy = _impact_object(_impact_object(manifest.get("extensions")).get("reviewPolicy"))
    if set(policy) - {"schemaVersion", "requiredSeats", "limits", "minimumDistinctSurfaces"}:
        raise LifecycleError("review-policy-invalid", "Unknown review policy")
    seats = policy.get("requiredSeats")
    if (
        policy.get("schemaVersion") != "agent-plan-review-policy.v1"
        or not isinstance(seats, list)
        or not 1 <= len(seats) <= 8
    ):
        raise LifecycleError("review-policy-invalid", "Required seats unavailable")
    ids = set()
    for seat in seats:
        seat = _impact_object(seat)
        identifier = seat.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise LifecycleError("review-policy-invalid", "Duplicate seat")
        ids.add(identifier)
        if not _impact_refs(seat, "allowedReviewerIds") or not _impact_refs(seat, "reports"):
            raise LifecycleError("review-policy-invalid", "Unbound seat")
        if any(seat.get(key) not in seat["reports"] for key in ("baseline", "current")):
            raise LifecycleError("review-policy-invalid", "Unbound selector")
    _review_limits(policy)
    return policy


def _review_limits(policy: dict[str, Any]) -> tuple[int, int, int]:
    limits = _impact_object(policy.get("limits", {}))
    result = []
    for key, cap in (
        ("reports", MAX_REVIEW_REPORTS),
        ("dependencyEdges", MAX_REVIEW_DEPENDENCY_EDGES),
        ("reportBytes", MAX_REVIEW_CHAIN_BYTES),
    ):
        value = limits.get(key, cap)
        if type(value) is not int or value < 1:
            raise LifecycleError("review-policy-invalid", "Invalid chain cap")
        result.append(min(value, cap))
    return result[0], result[1], result[2]


def validate_review_composition(
    manifest: dict[str, Any],
    envelope: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    *,
    report_sizes: dict[str, int],
) -> dict[str, Any]:
    """Verify declarations and coverage; never synthesize reviewer judgment.

    Filesystem callers must bind every supplied report and supporting artifact
    to stable contained bytes. Provenance remains DECLARED on ordinary hosts.
    """
    if (
        envelope.get("schemaVersion") != COMPOSITE_REVIEW_SCHEMA
        or envelope.get("fullReview") is not False
        or envelope.get("verdict") != "READY_TO_FREEZE"
        or envelope.get("reviewedPlanHash") != canonical_digest(manifest)
        or envelope.get("packageId") != manifest.get("package", {}).get("id")
        or envelope.get("planRevision") != manifest.get("planRevision")
    ):
        raise LifecycleError("review-composite-invalid", "Wrong composite subject")
    policy = review_policy(manifest)
    if envelope.get("currentReports") != [s["current"] for s in policy["requiredSeats"]]:
        raise LifecycleError("review-set-incomplete", "Wrong current selectors")
    paths = {path for seat in policy["requiredSeats"] for path in seat["reports"]}
    if set(reports) != paths or set(report_sizes) != paths:
        raise LifecycleError("review-set-incomplete", "Required reports differ")
    voices: set[str] = set()
    sessions: set[str] = set()
    surfaces: set[str] = set()
    results = []
    for seat in policy["requiredSeats"]:
        result = _validate_review_seat(manifest, seat, reports, report_sizes, policy)
        if voices & set(result["reviewerIds"]) or sessions & set(result["runIds"]):
            raise LifecycleError("review-duplicate-seat", "A voice cannot fill two seats")
        voices.update(result["reviewerIds"])
        sessions.update(result["runIds"])
        surfaces.add(result["surface"])
        results.append(result)
    diversity = policy.get("minimumDistinctSurfaces", 1)
    if type(diversity) is not int or diversity < 1 or len(surfaces) < diversity:
        raise LifecycleError("review-diversity-unsatisfied", "Missing diversity")
    scope = make_review_scope(results[0]["subject"])
    scope["kind"] = "COMPOSITE"
    if envelope.get("reviewScope") != scope:
        raise LifecycleError("review-scope-mismatch", "Wrong composite coverage")
    body = {
        "schemaVersion": "agent-plan-composition-validation.v1",
        "status": "PASS",
        "fullReview": False,
        "verdict": "READY_TO_FREEZE",
        "reviewedPlanHash": canonical_digest(manifest),
        "seats": results,
        "reviewerGuarantee": "DECLARED",
    }
    return {**body, "compositionDigest": canonical_digest(body)}


def _validate_review_seat(
    manifest: dict[str, Any],
    seat: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    sizes: dict[str, int],
    policy: dict[str, Any],
) -> dict[str, Any]:
    count_cap, depth_cap, bytes_cap = _review_limits(policy)
    paths = seat["reports"]
    if len(paths) > count_cap:
        raise LifecycleError("review-chain-limit", "Too many reports")
    if any(type(sizes[p]) is not int or sizes[p] < 1 for p in paths):
        raise LifecycleError("review-chain-invalid", "Invalid byte size")
    if sum(sizes[p] for p in paths) > bytes_cap:
        raise LifecycleError("review-chain-limit", "Report byte limit exceeded")
    by_digest: dict[str, dict[str, Any]] = {}
    identities: dict[tuple[str, str, str], str] = {}
    for path in paths:
        report = reports[path]
        validate_bound_plan_review(report)
        digest = canonical_digest(report)
        identity = (report["reviewId"], report["reviewer"]["id"], report["reviewer"]["runId"])
        if identity in identities and identities[identity] != digest:
            raise LifecycleError("review-redelivery-conflict", "Identity changed")
        identities[identity] = digest
        by_digest[digest] = report
    current = reports[seat["current"]]
    root = reports[seat["baseline"]]
    chain, cursor, seen = [], canonical_digest(current), set()
    while True:
        if cursor in seen or cursor not in by_digest:
            raise LifecycleError("review-chain-invalid", "Cycle or missing parent")
        seen.add(cursor)
        item = by_digest[cursor]
        chain.append((cursor, item))
        parents = _impact_refs(item, "dependsOn")
        if not parents:
            break
        if len(parents) != 1 or len(chain) > depth_cap:
            raise LifecycleError("review-chain-limit", "Unsupported dependency chain")
        cursor = parents[0]
    if seen != set(by_digest) or chain[-1][0] != canonical_digest(root):
        raise LifecycleError("review-set-incomplete", "Unaccounted required dissent")
    chain.reverse()
    _validate_seat_chain(seat, chain)
    subject = current["subject"]
    if subject["manifest"] != manifest:
        raise LifecycleError("review-subject-mismatch", "Stale final applicability")
    if current.get("verdict") != "READY_TO_FREEZE":
        raise LifecycleError("review-verdict-invalid", "Current acceptance missing")
    applicability = current.get("currentApplicability")
    expected = {
        "baselineDigest": None if canonical_digest(current) == canonical_digest(root) else canonical_digest(root),
        "candidateHash": canonical_digest(manifest),
        "completeCoverage": True,
        "unchangedBaselineApplicable": True,
        "allChangesReviewed": True,
        "allBlockingFindingsResolved": True,
    }
    if applicability != expected:
        raise LifecycleError("review-applicability-missing", "Explicit judgment needed")
    return {
        "seatId": seat["id"],
        "baselineDigest": canonical_digest(root),
        "currentDigest": canonical_digest(current),
        "reportCount": len(by_digest),
        "dependencyEdges": len(chain) - 1,
        "reviewerIds": sorted({r["reviewer"]["id"] for _, r in chain}),
        "runIds": sorted({r["reviewer"]["runId"] for _, r in chain}),
        "surface": current["reviewer"]["surface"],
        "subject": subject,
    }


def _validate_seat_chain(seat: dict[str, Any], chain: list[tuple[str, dict[str, Any]]]) -> None:
    pending: set[tuple[str, str]] = set()
    previous = None
    root_digest = chain[0][0]
    for digest, report in chain:
        reviewer = report["reviewer"]
        if reviewer["id"] not in seat["allowedReviewerIds"]:
            raise LifecycleError("review-replacement-unauthorized", "Wrong reviewer")
        if previous is None:
            if report["reviewScope"]["kind"] != "FULL":
                raise LifecycleError("review-incomplete", "Full baseline needed")
        else:
            if parse_reviewer_utc(report["reviewAuthority"]["completedAt"]) < parse_reviewer_utc(
                previous["reviewAuthority"]["completedAt"]
            ):
                raise LifecycleError("review-authority-invalid", "Reversed call chronology")
            selection = derive_delta_selection(previous["subject"], report["subject"])
            expected = make_review_scope(report["subject"], kind="DELTA", selection=selection)
            if report["reviewScope"] != expected:
                raise LifecycleError("review-impact-mismatch", "Impact not covered")
            if reviewer["id"] != previous["reviewer"]["id"] and (report.get("adoptsBaselineDigest") != root_digest):
                raise LifecycleError("review-replacement-unbound", "Adoption missing")
        closures = report.get("findingClosures", [])
        if not isinstance(closures, list) or len(closures) > 128:
            raise LifecycleError("review-closure-invalid", "Invalid closures")
        for closure in closures:
            if not isinstance(closure, dict):
                raise LifecycleError("review-closure-invalid", "Invalid closure")
            key = (closure.get("reportDigest"), closure.get("findingId"))
            if key not in pending or closure.get("status") != "CLOSED":
                raise LifecycleError("review-closure-invalid", "Unbound closure")
            _review_evidence(closure.get("evidence"))
            pending.remove(key)
        pending.update((digest, finding_id) for finding_id in open_blocking_finding_ids(report["findings"]))
        previous = report
    if pending:
        raise LifecycleError("review-open-findings", "Required dissent remains")
