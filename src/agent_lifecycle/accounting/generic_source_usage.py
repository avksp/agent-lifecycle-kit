"""Generic declared source reader over the existing durable publication kernel."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_lifecycle.accounting.declared_ledger import publish_declared_head
from agent_lifecycle.accounting.declared_source_route import canonical_source_bytes, read_carry_sources
from agent_lifecycle.accounting.usage_types import read_source_reference, source_reference
from agent_lifecycle.contracts import load_json_object
from agent_lifecycle.contracts.authority_io import create_authority_bytes, read_authority_bytes
from agent_lifecycle.contracts.declared_source_schemas import (
    DATA_LIMIT,
    require_declared,
    validate_project_carry,
    validate_project_head,
    validate_project_window,
)
from agent_lifecycle.contracts.scoped_usage_schemas import SOURCE_USAGE_ROLES


class GenericSourceUsage:
    """Selected only by frozen v2 inputs; this constructor grants no permission."""

    def __init__(self, selection: dict[str, Any]):
        self.selection = selection
        self.head_path = selection["policy"]["financialSource"]["headPath"]

    def read_current(self, owned_claim: tuple[bytes, int] | None = None) -> dict[str, Any]:
        root = self.selection["root"]
        policy = self.selection["policy"]
        seed = policy["financialSource"]["seedRef"]
        carry = validate_project_carry(
            load_json_object(read_source_reference(root, seed, limit=DATA_LIMIT), label="source carry")
        )
        require_declared(carry == self.selection["carry"], "selected carry changed")
        read_carry_sources(root, seed["path"], carry)
        read_source_reference(root, policy["sourceAuthoringRegistryRef"], limit=DATA_LIMIT)
        path = root / self.head_path
        pending = path.with_suffix(".pending.json")
        if owned_claim is None:
            require_declared(
                not pending.exists() and not pending.is_symlink(), "pending publication requires reconciliation"
            )
        else:
            raw, descriptor = owned_claim
            require_declared(
                os.path.samestat(os.fstat(descriptor), pending.lstat())
                and read_authority_bytes(pending, root=root, max_bytes=131_072) == raw,
                "pending publication claim changed",
            )
        raw = read_authority_bytes(path, root=root, max_bytes=DATA_LIMIT)
        result = self._read_chain(raw)
        require_declared(
            read_authority_bytes(path, root=root, max_bytes=DATA_LIMIT) == raw, "head changed during ancestry read"
        )
        return result

    def _read_chain(self, raw: bytes) -> dict[str, Any]:
        root, policy = self.selection["root"], self.selection["policy"]
        opening_ref = policy["openingRef"]
        head_raw = raw
        heads: list[dict[str, Any]] = []
        digests: list[str] = []
        while True:
            digest = hashlib.sha256(head_raw).hexdigest()
            require_declared(digest not in digests and len(heads) <= 128, "cyclic or oversized head chain")
            head = validate_project_head(load_json_object(head_raw, label="current declared head"))
            require_declared(
                head["seedSha256"] == policy["financialSource"]["seedRef"]["sha256"]
                and head["unknownIntervals"] == self.selection["carry"]["unknownIntervals"],
                "head changes seed or inherited UNKNOWN",
            )
            if heads:
                newer = heads[-1]
                require_declared(
                    newer["sequence"] == head["sequence"] + 1 and newer["windows"][:-1] == head["windows"],
                    "forked or truncated window ancestry",
                )
            heads.append(head)
            digests.append(digest)
            if head["sequence"] == 0:
                require_declared(
                    digest == opening_ref["sha256"]
                    and head_raw == read_source_reference(root, opening_ref, limit=DATA_LIMIT),
                    "chain omits frozen opening",
                )
                break
            require_declared(head["openingHeadSha256"] == opening_ref["sha256"], "foreign opening ancestor")
            previous_path = (
                Path(self.head_path).parent / "declared-source-head-history" / (head["previousHeadSha256"] + ".json")
            )
            head_raw = read_authority_bytes(root / previous_path, root=root, max_bytes=DATA_LIMIT)
            require_declared(
                hashlib.sha256(head_raw).hexdigest() == head["previousHeadSha256"], "ancestor bytes differ"
            )
        history = root / Path(self.head_path).parent / "declared-source-head-history"
        if history.exists() or history.is_symlink():
            require_declared(stat.S_ISDIR(history.lstat().st_mode), "head history is indirect")
            with os.scandir(history) as members:
                names: set[str] = set()
                for member in members:
                    require_declared(len(names) < 128 and member.is_file(follow_symlinks=False), "unsafe head history")
                    names.add(member.name)
            require_declared(
                names == {digest + ".json" for digest in digests[1:]}, "head rollback or foreign archived branch"
            )
        else:
            require_declared(len(digests) == 1, "head ancestry archive is absent")
        windows = []
        operations = set()
        window_ids: set[str] = set()
        source_root = policy["financialSource"]["sourceRoot"]
        for index, ref in enumerate(heads[0]["windows"]):
            full_ref = {**ref, "path": source_root + "/" + ref["path"]}
            window = validate_project_window(
                load_json_object(
                    read_source_reference(root, full_ref, limit=DATA_LIMIT), label="original declared window"
                )
            )
            binding = window["binding"]
            operation = tuple(
                binding[key] for key in ("runId", "packageId", "taskId", "attempt", "semanticOperationId")
            )
            require_declared(
                window["id"] not in window_ids
                and ref["path"] == "windows/" + window["id"] + ".json"
                and window["sequence"] == index + 1
                and window["openingSha256"] == opening_ref["sha256"]
                and window["previousHeadSha256"] == list(reversed(digests))[index]
                and operation not in operations,
                "duplicate or foreign original window",
            )
            operations.add(operation)
            window_ids.add(window["id"])
            windows.append({"sourceRef": full_ref, "source": window})
        return {
            "headRaw": raw,
            "headSha256": digests[0],
            "head": heads[0],
            "ancestryHeadSha256s": digests,
            "primaryCheckout": str(root),
            "windows": windows,
        }

    def project(self, current: dict[str, Any]) -> dict[str, Any]:
        prefix = self.selection["prefix"]
        pools = [
            {
                "windowId": row["source"]["id"],
                "admissionRef": row["sourceRef"],
                "binding": row["source"]["binding"],
                "declaredTokenHold": row["source"]["declaredTokenHold"],
                "eligibility": "CURRENT_ELIGIBLE",
            }
            for row in current["windows"]
        ]
        carry = self.selection["carry"]
        return {
            "schemaVersion": "alk-source-usage-current-registry.v1",
            "openingHeadSha256": self.selection["policy"]["openingRef"]["sha256"],
            "terminalHeadSha256": current["headSha256"],
            "terminalSourceRef": source_reference(self.head_path, current["headRaw"]),
            "frozenPrefixRawSha256": self.selection["policy"]["sourceAuthoringRegistryRef"]["sha256"],
            "records": [{"sourceRef": row["sourceRef"]} for row in current["windows"]],
            "windowPools": pools,
            "unknownIntervals": prefix["unknownIntervals"],
            "declaredUnitRecords": carry["declaredUnitRecords"],
            "knownPartials": carry["knownPartials"],
            "roleDispositions": [
                {
                    "role": role,
                    "status": "UNAVAILABLE",
                    "windowIds": [pool["windowId"] for pool in pools if pool["binding"]["role"] == role],
                }
                for role in SOURCE_USAGE_ROLES
            ],
            "balances": {"actualTokens": None, "actualInputTokens": None},
            "guarantee": "DECLARED_DERIVED_SOURCE_EVIDENCE_ONLY",
        }


def advance_project_source(
    selection: dict[str, Any],
    window: dict[str, Any],
    expected_head_sha256: str,
    *,
    precommit: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Publish one full immutable hold, preserving original UNKNOWN and ancestry."""
    validate_project_window(window)
    reader = GenericSourceUsage(selection)
    current = reader.read_current()
    root = selection["root"]
    source_root = selection["policy"]["financialSource"]["sourceRoot"]
    relative = "windows/" + window["id"] + ".json"
    raw = canonical_source_bytes(window)
    ref = source_reference(relative, raw)
    for prior in current["windows"]:
        if prior["source"]["binding"] == window["binding"]:
            require_declared(prior["source"] == window, "duplicate original identity differs")
            return current
    require_declared(
        current["headSha256"] == expected_head_sha256 == window["previousHeadSha256"]
        and window["sequence"] == current["head"]["sequence"] + 1
        and window["openingSha256"] == selection["policy"]["openingRef"]["sha256"],
        "stale publication frontier",
    )
    operation_keys = ("runId", "packageId", "taskId", "attempt", "semanticOperationId")
    require_declared(
        not any(
            all(row["source"]["binding"][key] == window["binding"][key] for key in operation_keys)
            for row in current["windows"]
        ),
        "operation already holds an original window",
    )
    full_path = source_root + "/" + relative
    try:
        create_authority_bytes(root / full_path, raw, root=root)
    except FileExistsError:
        require_declared(
            read_authority_bytes(root / full_path, root=root, max_bytes=DATA_LIMIT) == raw, "original window collision"
        )
    head = {
        **current["head"],
        "sequence": window["sequence"],
        "previousHeadSha256": current["headSha256"],
        "openingHeadSha256": selection["policy"]["openingRef"]["sha256"],
        "windows": [*current["head"]["windows"], ref],
    }
    validate_project_head(head)

    def recheck() -> None:
        if precommit is not None:
            precommit()
        require_declared(
            read_authority_bytes(root / reader.head_path, root=root, max_bytes=DATA_LIMIT) == current["headRaw"]
            and read_authority_bytes(root / full_path, root=root, max_bytes=DATA_LIMIT) == raw,
            "source/head changed before publication",
        )
        for key in ("openingRef", "sourceAuthoringRegistryRef"):
            read_source_reference(root, selection["policy"][key], limit=DATA_LIMIT)
        read_source_reference(root, selection["policy"]["financialSource"]["seedRef"], limit=DATA_LIMIT)

    return publish_declared_head(
        root=root,
        path=root / reader.head_path,
        previous_raw=current["headRaw"],
        next_raw=canonical_source_bytes(head),
        archive_name="declared-source-head-history",
        recheck=recheck,
        observe=reader.read_current,
    )
