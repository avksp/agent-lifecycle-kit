"""Owned source review history helpers."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger import (
    _R11_COORDINATOR_SEED,
    _r11_coordinator_head_value,
    _r11_coordinator_source,
    read_coordinator_cost_head,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _R11_REVIEW_ROOT,
    _r11_coordinator_root,
    _r11_review_private,
    _r11_role_cost_chain,
)
from agent_lifecycle.accounting.declared_ledger_records import _r11_role_identity, _r11_transport_binding, _require
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_ENTRYPOINT_PATH,
    _R11_REQUEST_CAP,
    _r11_review_directory,
    _r11_role_authority,
    _r11_role_request_seal,
    collect_source_review_shared,
    collect_source_review_threads,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import _r11_parent_snapshot, _r11_read_parent_file
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_integration_closure,
    _r11_role_request_candidate,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_private_support,
    _r11_support_authority,
    collect_source_review_support,
)
from agent_lifecycle.contracts import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.bounded_json import load_bounded_json as _r11_json
from agent_lifecycle.contracts.bounded_json import matches_closed_schema as _r11_role_schema_matches


def _r11_review_authorities(root: Path, *, role_delivery: bool = False) -> dict[str, Any]:
    """Bind the current terminal specification and retained R11 evidence ancestor."""
    _, _, route, authority = _r11_support_authority(root, role_delivery=role_delivery)
    prefix = "tasks/release-2-16/"
    lock_raw = read_authority_bytes(root / (prefix + "plan.lock.json"), root=root, max_bytes=2_097_152)
    lock = _r11_json(lock_raw, limit=2_097_152)
    _require(
        hashlib.sha256(lock_raw).hexdigest() == authority[prefix + "plan.lock.json"],
        "r11-review-authority",
        "installed lock changed",
    )
    entries = {entry["path"]: entry for entry in lock["entries"]}
    terminal_path = prefix + "r69l-r11-bootstrap-delta.md" if role_delivery else route["r11DeltaPath"]
    terminal_raw = read_authority_bytes(root / terminal_path, root=root, max_bytes=131_072)
    terminal_sha = hashlib.sha256(terminal_raw).hexdigest()
    _require(
        (role_delivery or terminal_sha == route["r11DeltaSha256"])
        and terminal_sha == entries.get(terminal_path, {}).get("sha256")
        and entries[terminal_path]["bytes"] == len(terminal_raw),
        "r11-review-authority",
        "terminal contract differs from installed lock",
    )
    parent_raw = {
        name: _r11_read_parent_file(root, root / _R11_REVIEW_ROOT / "parent-r69k" / name)
        for name in ("plan.lock.json", "plan.manifest.json", "independent-s2-review.json")
    }
    parent = {name: _r11_json(raw, limit=2_097_152) for name, raw in parent_raw.items()}
    expected = route["parent"]
    parent_entries = {row["path"]: row for row in parent["plan.lock.json"]["entries"]}
    review_entry = parent_entries.get(prefix + "independent-s2-review.json", {})
    _require(
        hashlib.sha256(parent_raw["plan.lock.json"]).hexdigest() == expected["lockSha256"]
        and hashlib.sha256(parent_raw["plan.manifest.json"]).hexdigest() == expected["manifestSha256"]
        and canonical_digest(parent["plan.manifest.json"])
        == expected["canonicalPlanDigest"]
        == parent["plan.lock.json"]["manifestHash"]
        and review_entry.get("sha256") == hashlib.sha256(parent_raw["independent-s2-review.json"]).hexdigest()
        and review_entry.get("bytes") == len(parent_raw["independent-s2-review.json"])
        and parent["independent-s2-review.json"].get("reviewedPlanHash") == expected["canonicalPlanDigest"]
        and parent["independent-s2-review.json"].get("manifestSha256") == expected["manifestSha256"],
        "r11-review-authority",
        "retained R11 ancestor lock/manifest/review lineage differs",
    )
    return {
        "installedAuthoritySha256": authority,
        "terminalContractSha256": terminal_sha,
        "terminalContractContent": terminal_raw.decode("utf-8"),
        "parentAuthoritySha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in parent_raw.items()},
        "parentPlanDigest": expected["canonicalPlanDigest"],
    }


def _r11_append_reconstructed_source_roles(
    projection: dict,
    source_content: list[dict],
    shared: dict,
    authorities: dict,
    authority: dict,
    exposures: dict[str, bytes],
    roles: list[dict],
    operation_ids: list[str] | None,
) -> None:
    for role, content in zip(projection["roles"], source_content, strict=False):
        _require(
            content["roleId"] == role["roleId"]
            and [row["extent"] for row in content["sourceContent"]] == role["sourceRanges"]
            and all(
                content[key] == role[key]
                for key in ("callProjection", "staticPairAssignment", "requiredIntegrationScopes")
            ),
            "r11-role-basis-join",
            "literal role content differs from independently rebuilt projection",
        )
        closure = _r11_role_integration_closure(
            shared["parentReviewRaw"],
            authorities["terminalContractContent"],
            authority,
            role["requiredIntegrationScopes"],
        )
        exposure = {
            **{key: value for key, value in content.items() if key != "roleId"},
            "integrationClosureContent": closure,
        }
        exposures[role["roleId"]] = canonical_bytes(exposure)
        roles.append(
            {
                "roleId": role["roleId"],
                "roleKind": "SOURCE",
                "exposureSha256": canonical_digest(exposure),
                "sourceRangeSha256": canonical_digest(role["sourceRanges"]),
                "callProjectionSha256": canonical_digest(role["callProjection"]),
                "staticPairAssignmentSha256": canonical_digest(role["staticPairAssignment"]),
                "requiredIntegrationScopes": role["requiredIntegrationScopes"],
            }
        )
    _require(
        isinstance(operation_ids, list)
        and len(operation_ids) == len(roles)
        and all(
            _r11_role_schema_matches(value, {"type": "string", "minLength": 1, "maxLength": 256})
            for value in operation_ids
        )
        and len(set(operation_ids)) == len(roles),
        "r11-role-operations",
        "one distinct bounded preassigned operation per shared/source role required",
    )


def _r11_reconstruct_review_basis(
    root: Path,
    review_id: str,
    *,
    source_basis: dict[str, Any],
    projection: dict[str, Any],
    source_content: list[dict[str, Any]],
    operation_ids: list[str],
) -> dict[str, Any]:
    """Join freshly produced SOURCE material to raw pre-funding SHARED evidence.

    Called by the current builder after its independent source projection. This
    is an immutable preparation candidate, not accepted SHARED, funded slots or
    an all-role collector. Funding/reservation/settlement joins remain separate.
    """
    directory = _r11_review_directory(root, review_id)
    authority = _r11_role_authority(root)
    authorities = _r11_review_authorities(root, role_delivery=True)
    origin = read_source_review_opening_origin(root, review_id=review_id, role_delivery=True)
    opening_raw = _r11_review_private(root, directory / "cost-opening.json")
    support = collect_source_review_support(
        root, support_directory=directory / "support", opening_raw=opening_raw, role_delivery=True
    )
    membership = source_basis["authority"]["privateMembership"]
    raw = _r11_private_support(root, directory / "support", membership["requiredKeys"])
    parent_raw, _ = _r11_parent_snapshot(root)
    parent, partition = source_basis["parent"], source_basis["partition"]
    subject = source_basis["subject"]
    current_authority = source_basis["authority"]["authoritySha256"]
    _require(
        support["authoritySha256"] == authorities["installedAuthoritySha256"] == current_authority
        and all(current_authority.get(name) == digest for name, digest in partition["authoritySha256"].items())
        and subject["authorityInventorySha256"] == canonical_digest(current_authority)
        and support["privateSupportReceiptDigests"]
        == {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
        and support["costOpeningSha256"] == origin["costOpeningSha256"] == hashlib.sha256(opening_raw).hexdigest()
        and hashlib.sha256(parent_raw["review-body.raw"]).hexdigest() == parent["parentReviewBodySha256"]
        and _r11_json(parent_raw["review-body.raw"], limit=65_536) == parent["content"]["parentBody"]
        and parent["parentVerdict"] == "FAIL"
        and projection["coverageUnionSha256"] == subject["sourceCoverageSha256"]
        and projection["interactionMatrixSha256"] == subject["sourceInteractionMatrixSha256"],
        "r11-role-basis-join",
        "source/support/parent/opening or projection identity differs",
    )
    shared = {
        "schemaVersion": "alk-r11-shared-exposure.v1",
        "parentReviewRaw": parent_raw["review-body.raw"].decode("utf-8"),
        "parentEvidence": parent["content"],
        "sourcePartition": partition,
        "sourceIdentities": [
            {"version": version, "path": name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            for (version, name), value in sorted(source_basis["sources"].items())
        ],
        "support": support["content"],
        "openingRaw": opening_raw.decode("utf-8"),
        "openingOrigin": origin,
        "retainedTerminalContractRaw": authorities["terminalContractContent"],
        "currentRoleRules": authority["contract"]["roleBodySemanticValidation"],
        "identityOnly": {
            "installedAuthoritySha256": current_authority,
            "retainedPlanAuthoritySha256": authorities["parentAuthoritySha256"],
            "privateSupportReceiptDigests": support["privateSupportReceiptDigests"],
        },
        "claimScope": "LIMITED_ALK_INPUT_PROCEDURAL_REVIEW",
    }
    base = {
        "schemaVersion": "alk-r11-role-base.v1",
        "reviewId": review_id,
        "planLockSha256": authority["lockSha256"],
        **{
            key: subject[key]
            for key in (
                "authorityInventorySha256",
                "parentSubjectSha256",
                "sourcePartitionSha256",
                "sourceSelectionSha256",
                "sourceGraphSha256",
                "sourceInteractionMatrixSha256",
            )
        },
        "sharedExposureSha256": canonical_digest(shared),
        "privateSupportMembershipSha256": current_authority["tasks/release-2-16/REQUIRED-PRIVATE-SUPPORT-v1.json"],
        "wipIdentitySha256": canonical_digest(support["content"]["wip"]),
        "testIdentitySha256": canonical_digest({key: support["content"][key] for key in ("tests", "caseMappings")}),
        "openingHeadSha256": origin["coordinatorHeadSha256"],
        "openingSourceSha256": support["costOpeningSha256"],
        "claimScope": shared["claimScope"],
        "limits": authority["contract"]["limits"],
    }
    empty = canonical_digest([])
    roles = [
        {
            "roleId": "shared-01",
            "roleKind": "SHARED",
            "exposureSha256": base["sharedExposureSha256"],
            "sourceRangeSha256": empty,
            "callProjectionSha256": empty,
            "staticPairAssignmentSha256": empty,
            "requiredIntegrationScopes": [],
        }
    ]
    exposures = {"shared-01": canonical_bytes(shared)}
    _require(
        len(source_content) == len(projection["roles"]), "r11-role-basis-join", "source role content count differs"
    )
    _r11_append_reconstructed_source_roles(
        projection, source_content, shared, authorities, authority, exposures, roles, operation_ids
    )
    operation_ids = _validated_cast(list[Any], operation_ids)
    inventory = {
        "schemaVersion": "alk-r11-role-inventory.v1",
        "reviewId": review_id,
        "baseSha256": canonical_digest(base),
        "roles": [{**role, "operationId": operation} for role, operation in zip(roles, operation_ids, strict=False)],
    }
    _require(
        _r11_role_schema_matches(base, authority["schemas"]["base"])
        and _r11_role_schema_matches(inventory, authority["schemas"]["roleInventory"]),
        "r11-role-basis-shape",
        "reconstructed immutable base/inventory violates the closed contract",
    )
    _require(
        _r11_role_authority(root) == authority
        and _r11_review_authorities(root, role_delivery=True) == authorities
        and read_source_review_opening_origin(root, review_id=review_id, role_delivery=True) == origin
        and _r11_review_private(root, directory / "cost-opening.json") == opening_raw
        and _r11_private_support(root, directory / "support", membership["requiredKeys"]) == raw
        and _r11_parent_snapshot(root)[0] == parent_raw,
        "r11-role-basis-stale",
        "raw authority/support/opening/parent changed during reconstruction",
    )
    return {
        "base": base,
        "baseRaw": canonical_bytes(base),
        "baseSha256": canonical_digest(base),
        "roleInventory": inventory,
        "roleInventoryRaw": canonical_bytes(inventory),
        "roleInventorySha256": canonical_digest(inventory),
        "roleExposureRaw": exposures,
        "sharedEvidenceAccepted": False,
        "fundingAdmitted": False,
        "dispatchAllowed": False,
        "firstNativeBootstrapEligible": False,
    }


def _r11_review_cost_basis(root: Path, review_id: str, *, role_delivery: bool = False) -> dict[str, Any]:
    _require(
        role_delivery is True, "r11-v5-runtime-retired", "current review execution requires explicit v6 role delivery"
    )
    _require(type(role_delivery) is bool, "r11-cost-mode", "explicit cost delivery mode required")
    directory = _r11_review_directory(root, review_id)
    pending = directory / "role-preparation.pending.json"
    _require(
        not pending.exists() and not pending.is_symlink(),
        "r11-role-preparation-pending",
        "partial immutable preparation cannot be funded or dispatched",
    )
    names = ("role-base.json", "role-inventory.json", "role-funding.json")
    raw = {name: _r11_review_private(root, directory / name) for name in names}
    authority = _r11_role_authority(root)
    identity = _r11_role_identity(
        authority=authority, base_raw=raw[names[0]], inventory_raw=raw[names[1]], funding_raw=raw[names[2]]
    )
    base, funding = identity["base"], identity["funding"]
    origin = read_source_review_opening_origin(root, review_id=review_id, role_delivery=True)
    proof = read_coordinator_cost_head(root, ancestor_head_sha256=origin["coordinatorHeadSha256"])
    prior = read_coordinator_cost_head(root, ancestor_head_sha256=funding["priorHeadSha256"])
    _require(
        base["reviewId"] == review_id
        and base["openingHeadSha256"] == origin["coordinatorHeadSha256"]
        and base["openingSourceSha256"] == origin["costOpeningSha256"]
        and funding["priorHeadSha256"] in proof["ancestryHeadSha256s"]
        and prior["headSha256"] == proof["headSha256"]
        and prior["ancestor"]["head"]["unknownHolds"] == funding["priorUnknownHolds"]
        and prior["ancestor"]["head"]["exposureLowerBound"] == funding["priorExposureLowerBound"]
        and funding["reusedFirstHold"] is None,
        "r11-role-cost-origin",
        "funding predecessor/balances differ or hold reuse lacks independent proof",
    )
    _require(
        all(
            raw[name] == canonical_bytes(identity[key])
            for name, key in zip(names, ("base", "inventory", "funding"), strict=False)
        )
        and all(_r11_review_private(root, directory / name) == value for name, value in raw.items())
        and _r11_role_authority(root) == authority
        and read_source_review_opening_origin(root, review_id=review_id, role_delivery=True) == origin
        and read_coordinator_cost_head(root, ancestor_head_sha256=funding["priorHeadSha256"]) == prior,
        "r11-role-cost-stale",
        "immutable role cost basis or coordinator provenance changed",
    )
    return {
        "identity": identity,
        "schemas": authority["schemas"],
        "rawSha256": {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
        "openingOrigin": origin,
        "coordinatorProof": prior,
        "fundingAdmitted": False,
    }


def _r11_cost_files(root: Path, review_id: str, *, role_ids: list[str] | None = None) -> dict[str, bytes]:
    _require(role_ids is not None, "r11-v5-runtime-retired", "cost files require the explicit v6 role inventory")
    if role_ids is not None:
        _require(
            isinstance(role_ids, list)
            and 2 <= len(role_ids) <= 33
            and role_ids == ["shared-01"] + [f"source-{i:02d}" for i in range(1, len(role_ids))],
            "r11-role-cost-storage",
            "exact ordered shared/source slots required",
        )
        role_ids = _validated_cast(list[Any], role_ids)
    expected = role_ids
    directory = _r11_review_directory(root, review_id) / "role-cost"
    if not directory.exists():
        _require(not directory.is_symlink(), "r11-cost-storage", "cost directory is indirect")
        return {}
    _require(
        stat.S_ISDIR(directory.lstat().st_mode) and directory.stat().st_mode & 0o077 == 0,
        "r11-cost-storage",
        "cost directory must be private and direct",
    )
    result = {}
    children = sorted(directory.iterdir())
    _require(
        len(children) <= len(_validated_cast(list[str], expected)), "r11-cost-storage", "cost role/shard bound exceeded"
    )
    for index, child in enumerate(children):
        _require(
            child.name == _validated_cast(list[str], expected)[index]
            and stat.S_ISDIR(child.lstat().st_mode)
            and child.stat().st_mode & 0o077 == 0,
            "r11-cost-storage",
            "missing, extra, indirect or nonprivate cost shard",
        )
        names = {path.name for path in child.iterdir()}
        _require(
            names in ({"reservation.json"}, {"reservation.json", "settlement.json"}),
            "r11-cost-uncertain",
            "cost publication is missing, partial or conflicted; no retry",
        )
        for name in sorted(names):
            result[child.name + "/" + name] = _r11_review_private(root, child / name)
    return result


def read_source_review_cost(project_root: Path, *, review_id: str, role_delivery: bool = False) -> dict[str, Any]:
    """Read anchored v6 role funding; never infer usage or opening origin."""
    _require(
        role_delivery is True, "r11-v5-runtime-retired", "current review execution requires explicit v6 role delivery"
    )
    root = Path(project_root).absolute()
    basis = _r11_review_cost_basis(root, review_id, role_delivery=role_delivery)
    ids = [role["roleId"] for role in basis["identity"]["inventory"]["roles"]]
    raw = _r11_cost_files(root, review_id, role_ids=ids)
    result = _r11_role_cost_chain(root, review_id, basis, raw)
    funding_origin = _r11_role_funding_origin(root, review_id, basis)
    receipt_raw = {}
    pending = _r11_review_directory(root, review_id) / "role-cost-prefix.pending.json"
    _require(
        not pending.exists() and not pending.is_symlink(),
        "r11-role-prefix-pending",
        "role-prefix publication is unresolved; no automatic retry",
    )
    if funding_origin is not None:
        pinned = funding_origin["costPrefix"]
        _require(
            pinned["prefixSha256"] == result["prefixSha256"] and pinned["costChainSha256"] == result["costChainSha256"],
            "r11-role-prefix-unanchored",
            "local role history is missing, changed or not globally anchored",
        )
        for step in pinned["steps"]:
            path = _r11_review_directory(root, review_id) / "role-prefix-receipts" / (step["costChainSha256"] + ".json")
            receipt_raw[path] = _r11_review_private(root, path)
            expected = {
                "schemaVersion": "alk-r11-role-prefix-origin.v1",
                "fundingBatchSha256": basis["identity"]["fundingBatchSha256"],
                **step,
            }
            _require(
                receipt_raw[path] == canonical_bytes(expected),
                "r11-role-prefix-receipt",
                "private role-prefix receipt differs from independently replayed global entry",
            )
    _require(
        _r11_review_cost_basis(root, review_id, role_delivery=True) == basis
        and _r11_cost_files(root, review_id, role_ids=ids) == raw
        and _r11_role_cost_chain(root, review_id, basis, raw) == result
        and _r11_role_funding_origin(root, review_id, basis) == funding_origin
        and all(_r11_review_private(root, path) == value for path, value in receipt_raw.items())
        and not pending.exists()
        and not pending.is_symlink(),
        "r11-role-cost-stale",
        "cost ancestors, raw prefixes, worker or coordinator changed during read",
    )
    if funding_origin is not None:
        result.update(
            status="ROLE_BUDGET_ADMITTED_PREFIX_MATCHED",
            fundingAdmitted=True,
            fundingOrigin=funding_origin,
            rolePrefixesAnchored=True,
            dispatchReservationQualified=False,
        )
    return result


def _r11_read_role_request_files(root: Path, directory: Path, names: set[str]) -> dict[str, bytes]:
    """Reassemble exact bounded bytes; reject missing, extra or indirect parts."""
    _require(
        directory.is_dir() and not directory.is_symlink(),
        "r11-role-request-files",
        "role request directory missing or indirect",
    )
    inventory = {path.name for path in directory.iterdir()}
    expected = set(names)
    parts = {}
    if "parts.json" in inventory:
        raw = _r11_review_private(root, directory / "parts.json")
        manifest = _r11_json(raw, limit=131_072)
        _require(
            set(manifest) == {"schemaVersion", "files"}
            and raw == canonical_bytes(manifest)
            and manifest["schemaVersion"] == "alk-r11-role-request-parts.v1"
            and isinstance(manifest["files"], dict)
            and bool(manifest["files"])
            and set(manifest["files"]) <= names,
            "r11-role-request-files",
            "closed canonical role-part manifest required",
        )
        parts = manifest["files"]
        expected.add("parts.json")
    values = {}
    for name in sorted(names):
        if name not in parts:
            values[name] = _r11_review_private(root, directory / name)
            continue
        row = parts[name]
        _require(
            isinstance(row, dict)
            and set(row) == {"bytes", "sha256", "parts"}
            and type(row["bytes"]) is int
            and 131_072 < row["bytes"] <= _R11_REQUEST_CAP
            and isinstance(row["sha256"], str)
            and re.fullmatch("[0-9a-f]{64}", row["sha256"]) is not None
            and isinstance(row["parts"], list)
            and len(row["parts"]) == (row["bytes"] + 65535) // 65536,
            "r11-role-request-files",
            "part count, total size or digest is invalid",
        )
        row = _validated_cast(dict[str, Any], row)
        expected.remove(name)
        pieces = []
        for index, digest in enumerate(row["parts"]):
            part_name = f"{name}.part-{index:02d}"
            expected.add(part_name)
            piece = _r11_review_private(root, directory / part_name)
            _require(
                len(piece) == min(65_536, row["bytes"] - index * 65_536)
                and hashlib.sha256(piece).hexdigest() == digest,
                "r11-role-request-files",
                "part length, order or digest differs",
            )
            pieces.append(piece)
        values[name] = b"".join(pieces)
        _require(
            hashlib.sha256(values[name]).hexdigest() == row["sha256"],
            "r11-role-request-files",
            "assembled role bytes differ",
        )
    _require(
        inventory == expected and {path.name for path in directory.iterdir()} == inventory,
        "r11-role-request-files",
        "sealed request is incomplete, pending, changed or has extra files",
    )
    return values


def _r11_role_request_origin(root: Path, review_id: str, binding: dict[str, str]) -> dict[str, Any]:
    """Bind the actual independently collected metadata thread, never a flag."""
    _r11_transport_binding(binding)
    operation = _r11_role_operation_start(root, review_id, binding["shardId"])
    metadata = collect_source_review_threads(root, review_id=review_id, role_id=binding["shardId"])
    start = operation["value"]
    cost = read_source_review_cost(root, review_id=review_id, role_delivery=True)
    _require(
        all(
            row["binding"]["threadId"] != binding["threadId"]
            for row in cost["reservations"]
            if row["binding"]["shardId"] != binding["shardId"]
        ),
        "r11-role-thread-reused",
        "role metadata reused another assigned model thread",
    )
    _require(
        metadata.get("status") == "ROLE_FRESH_EMPTY_THREAD_MATCHED"
        and metadata.get("metadataOriginQualified") is True
        and metadata.get("modelRequestsSent") == 0
        and metadata.get("modelDispatchAllowed") is False
        and metadata.get("reviewId") == review_id
        and metadata.get("roleId") == binding["shardId"]
        and metadata.get("operationId") == binding["operationId"] == start["operationId"]
        and metadata.get("threadIds") == [binding["threadId"]]
        and metadata.get("operationStartSha256") == operation["sha256"]
        and metadata.get("operationDeadlineUtc") == start["absoluteDeadlineUtc"]
        and metadata.get("operationDeadlineMonotonicNs") == start["deadlineMonotonicNs"]
        and all(metadata.get(key) == binding[key] for key in ("binarySha256", "transportSourceSha256"))
        and _r11_role_operation_start(root, review_id, binding["shardId"]) == operation
        and read_source_review_cost(root, review_id=review_id, role_delivery=True) == cost,
        "r11-role-request-origin",
        "actual metadata thread, source, operation or original deadline differs",
    )
    return {
        **({"sharedEvidenceSha256": start["sharedEvidenceSha256"]} if binding["shardId"] != "shared-01" else {}),
        "operationStartSha256": operation["sha256"],
        "metadataEvidenceSha256": metadata["evidenceSha256"],
        "threadId": binding["threadId"],
        "model": metadata["model"],
        "binarySha256": binding["binarySha256"],
        "transportSourceSha256": binding["transportSourceSha256"],
        "operationStartedAtUtc": start["startedAtUtc"],
        "absoluteDeadlineUtc": start["absoluteDeadlineUtc"],
        "operationStartedMonotonicNs": start["startedMonotonicNs"],
        "deadlineMonotonicNs": start["deadlineMonotonicNs"],
    }


def read_source_review_request(
    project_root: Path, *, review_id: str, role_id: str, require_reservation: bool = False
) -> dict[str, Any]:
    """Reconstruct sealed bytes; never attest source freshness, host or dispatch."""
    root = Path(project_root).absolute()
    _require(type(require_reservation) is bool, "r11-role-request-mode", "explicit reservation mode required")
    basis = _r11_review_cost_basis(root, review_id, role_delivery=True)
    roles = basis["identity"]["inventory"]["roles"]
    _require(any(row["roleId"] == role_id for row in roles), "r11-role-request-seal", "unknown role")
    directory = _r11_review_directory(root, review_id) / "role-requests" / role_id
    names = {"seal.json", "request.jsonl", "subject.json", "exposure.json"}
    if role_id != "shared-01":
        names |= {"shared-evidence.json", "shared-body.json"}

    def files():
        return _r11_read_role_request_files(root, directory, names)

    raw = files()
    seal = _r11_json(raw["seal.json"], limit=131_072)
    shared = collect_source_review_shared(root, review_id=review_id) if role_id != "shared-01" else None
    if shared is not None:
        _require(
            raw["shared-evidence.json"] == shared["evidenceRaw"] and raw["shared-body.json"] == shared["bodyRaw"],
            "r11-role-shared-unqualified",
            "SOURCE must carry independently accepted exact raw SHARED proof",
        )
    _require(
        all(key in seal for key in ("binding", "modelContextWindow", "sealedAtUtc")),
        "r11-role-request-seal",
        "request seal lacks binding/context/time",
    )
    _r11_transport_binding(seal["binding"])
    origin_bound = seal.get("schemaVersion") == "alk-r11-role-request-seal.v2-origin"
    _require(
        origin_bound or (seal.get("schemaVersion") == "alk-r11-role-request-seal.v1" and "metadataOrigin" not in seal),
        "r11-role-request-origin",
        "request origin generation differs",
    )
    metadata_origin = _r11_role_request_origin(root, review_id, seal["binding"]) if origin_bound else None
    candidate = _r11_role_request_candidate(
        root,
        base_raw=canonical_bytes(basis["identity"]["base"]),
        inventory_raw=canonical_bytes(basis["identity"]["inventory"]),
        funding_raw=canonical_bytes(basis["identity"]["funding"]),
        role_id=role_id,
        exposure_raw=raw["exposure.json"],
        thread_id=seal["binding"]["threadId"],
        model_context_window=seal["modelContextWindow"],
        shared_evidence_raw=raw.get("shared-evidence.json"),
        shared_body_raw=raw.get("shared-body.json"),
    )
    inputs = {name: value for name, value in raw.items() if name not in {"seal.json", "request.jsonl", "subject.json"}}
    expected = _r11_role_request_seal(
        basis,
        candidate,
        binding=seal["binding"],
        inputs=inputs,
        model_context_window=seal["modelContextWindow"],
        sealed_at=seal["sealedAtUtc"],
        metadata_origin=metadata_origin,
    )
    _require(
        raw["seal.json"] == canonical_bytes(expected)
        and raw["request.jsonl"] == candidate["requestRaw"]
        and raw["subject.json"] == canonical_bytes(candidate["subject"]),
        "r11-role-request-seal",
        "stored request/subject/seal differs from independently rebuilt bytes",
    )
    cost = read_source_review_cost(root, review_id=review_id, role_delivery=True)
    _require(
        cost.get("fundingAdmitted") is True and cost.get("rolePrefixesAnchored") is True,
        "r11-role-request-unfunded",
        "sealed bytes require current global funding and prefix origin",
    )
    if require_reservation:
        matches = [row for row in cost["reservations"] if row["roleId"] == role_id]
        _require(
            len(matches) == 1
            and matches[0]["binding"] == seal["binding"]
            and matches[0]["requestSha256"] == candidate["requestSha256"]
            and matches[0]["subjectSha256"] == candidate["subjectSha256"]
            and datetime.fromisoformat(matches[0]["reservedAtUtc"].replace("Z", "+00:00"))
            >= datetime.fromisoformat(seal["sealedAtUtc"].replace("Z", "+00:00")),
            "r11-role-request-reservation",
            "global reservation does not bind this sealed request",
        )
        if metadata_origin is not None:
            _require(
                datetime.fromisoformat(matches[0]["absoluteDeadlineUtc"].replace("Z", "+00:00"))
                == datetime.fromisoformat(metadata_origin["absoluteDeadlineUtc"].replace("Z", "+00:00")),
                "r11-role-request-reservation",
                "reservation reset the original metadata operation deadline",
            )
    _require(
        _r11_review_cost_basis(root, review_id, role_delivery=True) == basis
        and files() == raw
        and read_source_review_cost(root, review_id=review_id, role_delivery=True) == cost,
        "r11-role-request-stale",
        "immutable request, funding or cost prefix changed during read",
    )
    if metadata_origin is not None:
        _require(
            _r11_role_request_origin(root, review_id, seal["binding"]) == metadata_origin,
            "r11-role-request-stale",
            "metadata evidence changed during request reconstruction",
        )
    if shared is not None:
        _require(
            collect_source_review_shared(root, review_id=review_id) == shared,
            "r11-role-shared-stale",
            "accepted SHARED proof changed during SOURCE reconstruction",
        )
    return {
        **candidate,
        "status": "ROLE_REQUEST_SEALED_NOT_DISPATCHABLE",
        "seal": seal,
        "sealSha256": hashlib.sha256(raw["seal.json"]).hexdigest(),
        "reservationRequestMatched": require_reservation,
        "fundingAdmitted": True,
        "sourceFreshnessQualified": False,
        "selectedHostQualified": False,
        "dispatchAllowed": False,
    }


def _r11_role_funding_origin(root: Path, review_id: str, basis: dict[str, Any]) -> dict[str, Any] | None:
    directory = _r11_review_directory(root, review_id)
    receipt_path = directory / "role-funding-origin.json"
    pending = directory / "role-funding-origin.pending.json"
    _require(
        not pending.exists() and not pending.is_symlink(),
        "r11-role-funding-pending",
        "role funding publication is unresolved; no start or automatic retry",
    )
    if not receipt_path.exists():
        _require(not receipt_path.is_symlink(), "r11-role-funding-origin", "funding receipt is indirect")
        return None
    raw = _r11_review_private(root, receipt_path)
    receipt = _r11_json(raw, limit=131_072)
    _require(
        set(receipt) == {"schemaVersion", "headSha256", "sourcePath", "sourceSha256", "fundingBatchSha256"}
        and receipt["schemaVersion"] == "alk-r11-role-funding-origin.v1"
        and receipt["fundingBatchSha256"] == basis["identity"]["fundingBatchSha256"],
        "r11-role-funding-origin",
        "funding receipt differs from immutable batch",
    )
    primary = _r11_coordinator_root(root)
    seed, seed_raw = _r11_coordinator_source(primary, _R11_COORDINATOR_SEED)
    seed_head = canonical_digest(_r11_coordinator_head_value(_R11_COORDINATOR_SEED, seed_raw, seed, None))
    history = read_coordinator_cost_head(root, ancestor_head_sha256=seed_head)
    anchor = read_coordinator_cost_head(root, ancestor_head_sha256=receipt["headSha256"])
    expected = anchor["ancestor"]
    source = expected["source"]
    _require(
        history["headSha256"] == anchor["headSha256"] == basis["coordinatorProof"]["headSha256"]
        and any(row["headSha256"] == receipt["headSha256"] for row in history.get("roleFundingAdmissions", []))
        and receipt["sourcePath"] == expected["head"]["sourcePath"]
        and receipt["sourceSha256"] == expected["head"]["sourceSha256"]
        and source.get("schemaVersion") == "alk-r11-global-role-funding.v1"
        and all(
            source[key].encode("utf-8") == canonical_bytes(basis["identity"][field])
            for key, field in (("baseRaw", "base"), ("inventoryRaw", "inventory"), ("fundingRaw", "funding"))
        )
        and raw == canonical_bytes(receipt)
        and _r11_review_private(root, receipt_path) == raw
        and read_coordinator_cost_head(root, ancestor_head_sha256=seed_head) == history,
        "r11-role-funding-origin",
        "funding is absent, changed, duplicated, stale or not on the global ledger",
    )
    return {
        "receipt": receipt,
        "receiptSha256": hashlib.sha256(raw).hexdigest(),
        "costPrefix": history["roleCostPrefixes"][basis["identity"]["fundingBatchSha256"]],
        "currentHeadSha256": history["headSha256"],
        "unknownHolds": history["head"]["unknownHolds"],
        "exposureLowerBound": history["head"]["exposureLowerBound"],
        "admissionScope": "DECLARED_GLOBAL_ROLE_BUDGET_SINCE_PINNED_SEED",
        "measurementQualified": False,
        "wholeHistoryComplete": False,
        "hardCapClaim": "DENY",
    }


def read_source_review_opening_origin(
    project_root: Path, *, review_id: str, role_delivery: bool = False
) -> dict[str, Any]:
    """Reopen the imported origin; v6 permits proved subsequent coordinator edges.

    Returned identity and balances always describe the immutable opening, never
    today's head. This keeps the base stable across allowed later appends. The
    dispatcher still needs the independent current funding/reservation ledger.
    """
    _require(type(role_delivery) is bool, "r11-opening-version", "explicit delivery version required")
    root = Path(project_root).absolute()
    directory = _r11_review_directory(root, review_id)
    raw = _r11_review_private(root, directory / "cost-opening.json")
    receipt_raw = _r11_review_private(root, directory / "cost-opening-origin.json")
    receipt = _r11_json(receipt_raw, limit=131_072)
    if role_delivery:
        _require(isinstance(receipt.get("headSha256"), str), "r11-opening-ancestry", "pinned opening digest missing")
        snapshot = read_coordinator_cost_head(root, ancestor_head_sha256=receipt["headSha256"])
        origin = snapshot["ancestor"]
    else:
        snapshot = origin = read_coordinator_cost_head(root)
    expected = {
        key: origin[key]
        for key in (
            "schemaVersion",
            "status",
            "primaryCheckout",
            "head",
            "headSha256",
            "measurementQualified",
            "wholeHistoryComplete",
            "hardCapClaim",
        )
    }
    _require(
        raw == origin["sourceRaw"]
        and canonical_bytes(receipt) == canonical_bytes(expected)
        and _r11_review_private(root, directory / "cost-opening.json") == raw
        and _r11_review_private(root, directory / "cost-opening-origin.json") == receipt_raw
        and (
            read_coordinator_cost_head(root, ancestor_head_sha256=receipt["headSha256"])
            if role_delivery
            else read_coordinator_cost_head(root)
        )
        == snapshot,
        "r11-opening-stale",
        "imported opening or its current provenance changed",
    )
    return {
        "schemaVersion": "alk-r11-opening-origin-match.v1",
        "status": "DECLARED_OPENING_ORIGIN_MATCHED",
        "costOpeningSha256": hashlib.sha256(raw).hexdigest(),
        "originReceiptSha256": hashlib.sha256(receipt_raw).hexdigest(),
        "coordinatorHeadSha256": origin["headSha256"],
        "sourcePath": origin["head"]["sourcePath"],
        "unknownHolds": origin["head"]["unknownHolds"],
        "exposureLowerBound": origin["head"]["exposureLowerBound"],
        "openingProvenanceQualified": True,
        "provenanceScope": "PINNED_PRIMARY_COORDINATOR_ANCESTRY"
        if role_delivery
        else "CURRENT_PRIMARY_COORDINATOR_FILE",
        "measurementQualified": False,
        "wholeHistoryComplete": False,
        "hardCapClaim": "DENY",
        "firstNativeBootstrapEligible": False,
    }


def _r11_catalog_value(version_raw: bytes, catalog_raw: bytes, binary_sha: str, model: str) -> dict[str, Any]:
    """The selected bundled window is a candidate, never the actual hidden input."""
    _require(len(version_raw) <= 1024, "r11-catalog-version", "version output is oversized")
    version = version_raw.decode("utf-8").strip()
    catalog = _r11_json(catalog_raw, limit=1_048_576)
    _require(
        bool(version)
        and len(version) <= 256
        and isinstance(catalog.get("models"), list)
        and isinstance(model, str)
        and 0 < len(model) <= 256,
        "r11-catalog-shape",
        "bounded version, model and bundled catalog required",
    )
    model = _validated_cast(str, model)
    rows = [row for row in catalog["models"] if isinstance(row, dict) and row.get("slug") == model]
    _require(
        len(rows) == 1 and type(rows[0].get("context_window")) is int and rows[0]["context_window"] >= 16384,
        "r11-catalog-model",
        "selected bundled model/window is missing, ambiguous or invalid",
    )
    return {
        "source": "SELECTED_BINARY_BUNDLED_CATALOG_CANDIDATE",
        "binarySha256": binary_sha,
        "version": version,
        "catalogSha256": hashlib.sha256(catalog_raw).hexdigest(),
        "model": model,
        "modelEntryDigest": canonical_digest(rows[0]),
        "catalogWindowTokens": rows[0]["context_window"],
        "actualChildWindow": "UNPROVEN",
    }


def read_source_review_catalog(project_root: Path, *, review_id: str) -> dict[str, Any]:
    """Reopen exact raw bundled outputs and binary; full host context stays unknown."""
    from .codex_input_diagnostics import _file_sha

    root = Path(project_root).absolute()
    directory = _r11_review_directory(root, review_id) / "catalog"
    claim_raw = _r11_review_private(root, directory / "capture.json")
    observed_raw = _r11_review_private(root, directory / "observation.json")
    claim, observed = (_r11_json(raw, limit=131_072) for raw in (claim_raw, observed_raw))
    binary = Path(claim.get("binaryPath", ""))
    _require(
        set(claim)
        == {
            "schemaVersion",
            "reviewId",
            "binaryPath",
            "binarySha256",
            "model",
            "collectorSourceSha256",
            "commands",
            "modelRequestsAuthorized",
            "retryAuthorized",
        }
        and claim["schemaVersion"] == "alk-r11-catalog-capture.v1"
        and claim["reviewId"] == review_id
        and binary.is_absolute()
        and binary.name == "codex"
        and binary.resolve(strict=True) == binary
        and _file_sha(binary) == claim["binarySha256"]
        and _file_sha(_R11_ENTRYPOINT_PATH) == claim["collectorSourceSha256"]
        and claim["commands"] == [[str(binary), "--version"], [str(binary), "debug", "models", "--bundled"]]
        and type(claim["modelRequestsAuthorized"]) is int
        and claim["modelRequestsAuthorized"] == 0
        and claim["retryAuthorized"] is False,
        "r11-catalog-identity",
        "catalog source, selected binary or diagnostic identity differs",
    )
    parts = observed.get("catalogParts")
    _require(
        set(observed) == {"captureSha256", "catalogParts", "versionSha256", "selected"}
        and observed["captureSha256"] == canonical_digest(claim)
        and isinstance(parts, list)
        and 1 <= len(parts) <= 16
        and parts == [f"models-{i:02d}.raw" for i in range(len(parts))]
        and {p.name for p in directory.iterdir()} == {"capture.json", "observation.json", "version.raw", *parts},
        "r11-catalog-inventory",
        "missing, extra or partial catalog evidence",
    )
    parts = _validated_cast(list[Any], parts)
    raw = {name: _r11_review_private(root, directory / name) for name in ["version.raw", *parts]}
    _require(
        all(len(raw[name]) == 65536 for name in parts[:-1]) and 0 < len(raw[parts[-1]]) <= 65536,
        "r11-catalog-inventory",
        "catalog chunk lengths differ",
    )
    catalog = b"".join(raw[name] for name in parts)
    selected = _r11_catalog_value(raw["version.raw"], catalog, claim["binarySha256"], claim["model"])
    _require(
        selected == observed["selected"]
        and hashlib.sha256(raw["version.raw"]).hexdigest() == observed["versionSha256"]
        and _r11_review_private(root, directory / "capture.json") == claim_raw
        and _r11_review_private(root, directory / "observation.json") == observed_raw
        and all(_r11_review_private(root, directory / name) == value for name, value in raw.items())
        and _file_sha(binary) == claim["binarySha256"]
        and {p.name for p in directory.iterdir()} == {"capture.json", "observation.json", "version.raw", *parts},
        "r11-catalog-stale",
        "raw catalog, observation, inventory or binary changed",
    )
    return {
        "schemaVersion": "alk-r11-bundled-catalog-match.v1",
        "status": "BUNDLED_CATALOG_MATCHED",
        "binaryPath": str(binary),
        "selected": selected,
        "evidenceSha256": canonical_digest(
            {
                **{name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
                "capture.json": hashlib.sha256(claim_raw).hexdigest(),
                "observation.json": hashlib.sha256(observed_raw).hexdigest(),
            }
        ),
        "hostHiddenInput": "UNPROVEN",
        "actualChildWindow": "UNPROVEN",
        "firstNativeBootstrapEligible": False,
    }


def _r11_require_fresh_review_catalog(root: Path, *, review_id: str) -> dict[str, Any]:
    """Run inside the supervised child, under its original process deadline."""
    from .codex_input_diagnostics import _observed_bundled_catalog

    before = read_source_review_catalog(root, review_id=review_id)
    binary = before["binaryPath"]
    identity = {
        "status": "PASS",
        "resolvedPathSha256": hashlib.sha256(os.fsencode(binary)).hexdigest(),
        "executableContentSha256": before["selected"]["binarySha256"],
    }
    fresh = _observed_bundled_catalog(root, binary, identity, before["selected"]["model"], dict(os.environ))
    _require(
        fresh == before["selected"] and read_source_review_catalog(root, review_id=review_id) == before,
        "r11-catalog-stale",
        "fresh selected-binary catalog differs before host/model launch",
    )
    return before


def _r11_role_operation_start(root: Path, review_id: str, role_id: str) -> dict[str, Any]:
    """Reopen the original, immutable local operation clock and funded role."""
    _require(
        isinstance(role_id, str) and re.fullmatch(r"shared-01|source-(0[1-9]|[12][0-9]|3[0-2])", role_id) is not None,
        "r11-role-metadata-source",
        "exact bounded role selector required",
    )
    role_id = _validated_cast(str, role_id)
    path = _r11_review_directory(root, review_id) / "role-operations" / role_id / "start.json"
    raw = _r11_review_private(root, path)
    value = _r11_json(raw, limit=131_072)
    basis = _r11_review_cost_basis(root, review_id, role_delivery=True)
    identity = basis["identity"]
    funding = identity["funding"]
    matches = [(i, r) for i, r in enumerate(identity["inventory"]["roles"]) if r["roleId"] == role_id]
    _require(len(matches) == 1, "r11-role-operation-origin", "role absent from immutable funded inventory")
    index, role = matches[0]
    shared = collect_source_review_shared(root, review_id=review_id) if index else None
    keys = {
        "schemaVersion",
        "reviewId",
        "roleId",
        "operationId",
        "baseSha256",
        "roleInventorySha256",
        "fundingBatchSha256",
        "startedAtUtc",
        "absoluteDeadlineUtc",
        "startedMonotonicNs",
        "deadlineMonotonicNs",
    }
    if shared is not None:
        keys.add("sharedEvidenceSha256")
        _require(
            value.get("sharedEvidenceSha256") == hashlib.sha256(shared["evidenceRaw"]).hexdigest(),
            "r11-role-shared-unqualified",
            "SOURCE operation differs from independently accepted SHARED",
        )
    _require(
        set(value) == keys
        and raw == canonical_bytes(value)
        and value["schemaVersion"] == "alk-r11-role-operation-start.v1"
        and value["reviewId"] == review_id
        and value["roleId"] == role["roleId"] == role_id
        and value["operationId"] == role["operationId"]
        and all(value[key] == identity[key] for key in ("baseSha256", "roleInventorySha256", "fundingBatchSha256"))
        and all(type(value[key]) is int and value[key] > 0 for key in ("startedMonotonicNs", "deadlineMonotonicNs"))
        and all(
            _r11_role_schema_matches(value[key], {"type": "string", "format": "date-time", "maxLength": 40})
            for key in ("startedAtUtc", "absoluteDeadlineUtc")
        ),
        "r11-role-operation-origin",
        "closed original role clock differs from immutable funded ancestors",
    )
    start = datetime.fromisoformat(value["startedAtUtc"])
    end = datetime.fromisoformat(value["absoluteDeadlineUtc"])
    batch_start = datetime.fromisoformat(funding["admittedAtUtc"].replace("Z", "+00:00"))
    batch_end = datetime.fromisoformat(funding["absoluteDeadlineUtc"].replace("Z", "+00:00"))
    _require(
        batch_start
        <= start
        < end
        == min(start + timedelta(seconds=funding["slots"][index]["maxElapsedSeconds"]), batch_end)
        and value["deadlineMonotonicNs"]
        == value["startedMonotonicNs"] + int((end - start).total_seconds() * 1_000_000_000)
        and _r11_review_private(root, path) == raw
        and _r11_review_cost_basis(root, review_id, role_delivery=True) == basis,
        "r11-role-operation-deadline",
        "original role deadline was extended, changed or lies outside the batch",
    )
    if shared is not None:
        _require(
            collect_source_review_shared(root, review_id=review_id) == shared,
            "r11-role-shared-stale",
            "SHARED changed during SOURCE operation reconstruction",
        )
    return {"value": value, "sha256": hashlib.sha256(raw).hexdigest()}
