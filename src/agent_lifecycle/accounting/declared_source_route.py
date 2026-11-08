"""Registered project source selection and data-only opening preparation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from agent_lifecycle.accounting.usage_types import read_source_reference, source_reference
from agent_lifecycle.contracts import canonical_bytes, load_json_object
from agent_lifecycle.contracts.authority_io import create_authority_bytes, open_authority_read, read_authority_bytes
from agent_lifecycle.contracts.declared_source_schemas import (
    DATA_LIMIT,
    PROJECT_HEAD,
    PROJECT_PREFIX,
    SOURCE_BLOB_LIMIT,
    require_declared,
    validate_owner_bindings,
    validate_project_carry,
    validate_project_head,
    validate_project_policy,
    validate_project_prefix,
)
from agent_lifecycle.contracts.paths import normalize_repo_path


def canonical_source_bytes(value: dict[str, Any]) -> bytes:
    raw = canonical_bytes(value) + b"\n"
    require_declared(len(raw) <= DATA_LIMIT, "serialized declared source exceeds data bound")
    return raw


def read_source_object(root: Path, path: str) -> dict[str, Any]:
    return load_json_object(
        read_authority_bytes(root / normalize_repo_path(path), root=root, max_bytes=DATA_LIMIT),
        label="declared source data",
    )


def read_carry_sources(root: Path, seed_path: str, carry: dict[str, Any]) -> list[tuple[str, bytes]]:
    """Snapshot paths are seed-relative; originalPath remains an opaque label."""
    result = []
    directory = Path(seed_path).parent
    for source in carry["sourceRefs"]:
        path = (directory / source["path"]).as_posix()
        ref = {key: source[key] for key in ("path", "sha256", "bytes")}
        ref["path"] = path
        digest = hashlib.sha256()
        chunks = []
        count = 0
        with open_authority_read(root / path, root=root) as stream:
            while chunk := stream.read(65_536):
                count += len(chunk)
                require_declared(count <= SOURCE_BLOB_LIMIT and count <= ref["bytes"], "source blob exceeds bound")
                digest.update(chunk)
                chunks.append(chunk)
        raw = b"".join(chunks)
        require_declared(count == ref["bytes"] and digest.hexdigest() == ref["sha256"], "source blob bytes differ")
        result.append((source["path"], raw))
    return result


def prepare_project_opening(
    root: Path,
    *,
    carry_path: str,
    owner_bindings_path: str,
    opening_out: str,
    source_root: str,
) -> dict[str, Any]:
    """Create reviewed input data only; no child state, permit or host action."""
    for path in (carry_path, owner_bindings_path, opening_out, source_root):
        require_declared(normalize_repo_path(path) == path, "opening path is not canonical")
    require_declared(
        not (
            opening_out == source_root
            or opening_out.startswith(source_root + "/")
            or source_root.startswith(opening_out + "/")
        ),
        "mutable and immutable roots overlap",
    )
    carry = validate_project_carry(read_source_object(root, carry_path))
    owners = validate_owner_bindings(read_source_object(root, owner_bindings_path))
    blobs = read_carry_sources(root, carry_path, carry)
    seed_raw = canonical_source_bytes(carry)
    seed_ref = source_reference(opening_out + "/carry.json", seed_raw)
    head = {
        "schemaVersion": PROJECT_HEAD,
        "seedSha256": seed_ref["sha256"],
        "sequence": 0,
        "previousHeadSha256": None,
        "openingHeadSha256": None,
        "windows": [],
        "unknownIntervals": carry["unknownIntervals"],
        "financialClosure": "OPEN_UNAVAILABLE",
    }
    validate_project_head(head)
    head_raw = canonical_source_bytes(head)
    opening_ref = source_reference(opening_out + "/opening-head.json", head_raw)
    prefix = {
        "schemaVersion": PROJECT_PREFIX,
        "openingHeadSha256": opening_ref["sha256"],
        "requiredRoles": owners["requiredRoles"],
        "ownerBindings": owners["ownerBindings"],
        "historicalSourceRefs": [seed_ref],
        "unknownIntervals": carry["unknownIntervals"],
    }
    validate_project_prefix(prefix)
    prefix_raw = canonical_source_bytes(prefix)
    outputs = [(opening_out + "/" + path, raw) for path, raw in blobs]
    outputs += [
        (seed_ref["path"], seed_raw),
        (opening_ref["path"], head_raw),
        (opening_out + "/prefix.json", prefix_raw),
        (opening_out + "/owner-bindings.json", canonical_source_bytes(owners)),
        (source_root + "/HEAD.json", head_raw),
    ]
    require_declared(len({path for path, _ in outputs}) == len(outputs), "opening output collision")
    for path, _ in outputs:
        require_declared(not (root / path).exists() and not (root / path).is_symlink(), "opening output exists")
    # Reobserve original inputs immediately before publishing create-only data.
    require_declared(
        validate_project_carry(read_source_object(root, carry_path)) == carry
        and validate_owner_bindings(read_source_object(root, owner_bindings_path)) == owners
        and read_carry_sources(root, carry_path, carry) == blobs,
        "opening inputs changed",
    )
    for path, raw in outputs:
        create_authority_bytes(root / path, raw, root=root)
    return {
        "status": "SOURCE_DATA_ONLY",
        "openingRef": opening_ref,
        "sourceAuthoringRegistryRef": source_reference(opening_out + "/prefix.json", prefix_raw),
        "financialSource": {
            "route": "declared-project-source-v1",
            "sourceRoot": source_root,
            "headPath": source_root + "/HEAD.json",
            "seedRef": seed_ref,
        },
        "executionAuthorized": False,
        "actualTokens": None,
        "actualUSD": None,
    }


def select_project_source(selection: dict[str, Any], entries: dict[str, Any]) -> dict[str, Any]:
    """Validate immutable inputs after the caller verified the actual plan lock."""
    root, policy = selection["root"], validate_project_policy(selection["policy"])
    source = policy["financialSource"]
    seed_ref = source["seedRef"]
    require_declared(entries.get(seed_ref["path"]) == seed_ref, "seed outside frozen inventory")
    require_declared(
        source["headPath"] not in entries and not any(path.startswith(source["sourceRoot"] + "/") for path in entries),
        "mutable source root must not be frozen",
    )
    carry = validate_project_carry(
        load_json_object(read_source_reference(root, seed_ref, limit=DATA_LIMIT), label="frozen source carry")
    )
    for path, raw in read_carry_sources(root, seed_ref["path"], carry):
        full_path = (Path(seed_ref["path"]).parent / path).as_posix()
        require_declared(
            entries.get(full_path) == source_reference(full_path, raw), "snapshot outside frozen inventory"
        )
    prefix, opening = validate_project_prefix(selection["prefix"]), validate_project_head(selection["opening"])
    require_declared(
        opening["sequence"] == 0
        and opening["seedSha256"] == seed_ref["sha256"]
        and opening["unknownIntervals"] == carry["unknownIntervals"]
        and prefix["unknownIntervals"] == carry["unknownIntervals"]
        and prefix["historicalSourceRefs"] == [seed_ref],
        "opening loses carry or UNKNOWN",
    )
    owners_path = (Path(seed_ref["path"]).parent / "owner-bindings.json").as_posix()
    owner_ref = entries.get(owners_path)
    require_declared(isinstance(owner_ref, dict), "owner attribution input outside frozen inventory")
    owner_ref = cast(dict[str, Any], owner_ref)
    owner_input = validate_owner_bindings(
        load_json_object(read_source_reference(root, owner_ref, limit=DATA_LIMIT), label="frozen owner bindings")
    )
    require_declared(
        owner_input["ownerBindings"] == prefix["ownerBindings"]
        and owner_input["requiredRoles"] == prefix["requiredRoles"],
        "prefix attribution differs",
    )
    owners = {row["id"]: row["owner"] for row in selection["manifest"]["workstreams"]}
    attributed = set()
    for owner in prefix["ownerBindings"]:
        for task_id in owner["taskIds"]:
            require_declared(owners.get(task_id) == owner["actorId"], "attribution differs from frozen owner")
            attributed.add(task_id)
    require_declared(set(policy["taskIds"]) <= attributed, "source task lacks frozen attribution")
    return {**selection, "carry": carry, "registryByteLimit": 1_048_576}


def project_owner(selection: dict[str, Any], task_id: str) -> tuple[str, str]:
    matches = [row for row in selection["prefix"]["ownerBindings"] if task_id in row["taskIds"]]
    require_declared(len(matches) == 1, "task owner attribution is ambiguous")
    return matches[0]["actorId"], matches[0]["role"]


def project_binding(
    selection: dict[str, Any], state: dict[str, Any], task: dict[str, Any], window_id: str
) -> dict[str, Any]:
    """Compute subject independently from actual adopted state and frozen owner."""
    from agent_lifecycle.contracts.canonical import canonical_digest
    from agent_lifecycle.contracts.declared_source_schemas import PROJECT_BINDING, validate_project_binding

    actor, role = project_owner(selection, task["id"])
    route = task.get("attemptModelRoute")
    if task.get("status") == "ACCEPTED":
        require_declared(route is None, "accepted task retains active route")
        route = task.get("modelRoute")
    route = route or {}
    stage = task.get("attemptExecutionStrategy", {}).get("stageBinding")
    subject = {
        "taskPacketHash": task.get("packet", {}).get("sha256"),
        "planDigest": state["planDigest"],
        "sourceRevision": state["sourceRevision"],
        "routeDecisionDigest": route.get("decisionDigest"),
        "semanticOperationId": route.get("operationId"),
        "stageBindingDigest": canonical_digest(stage) if stage is not None else None,
    }
    require_declared(bool(subject["taskPacketHash"]), "current task packet hash absent")
    binding = {key: state[key] for key in ("runId", "packageId", "planDigest", "sourceRevision")}
    binding.update(
        schemaVersion=PROJECT_BINDING,
        bindingKind="PROJECT_DECLARED_SOURCE",
        semanticOperationId=route.get("operationId"),
        routeDecisionDigest=route.get("decisionDigest"),
        taskId=task["id"],
        attempt=task["attempt"],
        actorId=actor,
        role=role,
        sourceUsagePolicyDigest=selection["policyDigest"],
        originalWindowId=window_id,
        originalCostScope="SOURCE_AUTHORING_LIMITED",
        sourceInputSubjectDigest=canonical_digest(subject),
    )
    return validate_project_binding(binding)


def project_token_hold(task: dict[str, Any]) -> int:
    caps = [
        summary["resourceCaps"].get("maxBillableTokens")
        for summary in (task.get("attemptRiskExecutionProfile"), task.get("attemptExecutionStrategy"))
        if isinstance(summary, dict) and isinstance(summary.get("resourceCaps"), dict)
    ]
    require_declared(
        bool(caps) and all(type(cap) is int and cap > 0 for cap in caps), "full original token hold unavailable"
    )
    return cast(int, max(caps))
