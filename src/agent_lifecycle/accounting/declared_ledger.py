"""Declared accounting head transitions and monotonic full-hold replay. Separate from the H04 SQLite journal."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_coordinator_root,
    _r11_role_cost_chain,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _R11_COORDINATOR_BASE,
    _r11_role_funding_record,
    _r11_role_prefix_record,
    _require,
)
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import normalize_authority_path, read_authority_bytes
from agent_lifecycle.contracts.bounded_json import load_bounded_json as _r11_json

_R11_COORDINATOR_HEAD = _R11_COORDINATOR_BASE + "/COORDINATOR-COST-HEAD.json"


_R11_COORDINATOR_SEED = _R11_COORDINATOR_BASE + "/r396-r11-host-supervision-join/cost.json"


_R11_COORDINATOR_SEED_SHA = "b8272f68c9c7a6d24a099fe9db198bb944d57ef65db90a678edb707fcf365b9c"


def _r11_coordinator_head_value(
    source_path: str, source_raw: bytes, value: dict[str, Any], previous_head_sha256: str | None
) -> dict[str, Any]:
    return {
        "schemaVersion": "alk-r11-coordinator-cost-head.v1",
        "sourcePath": source_path,
        "sourceSha256": hashlib.sha256(source_raw).hexdigest(),
        "previousHeadSha256": previous_head_sha256,
        "seedSha256": _R11_COORDINATOR_SEED_SHA,
        "unknownHolds": value["unknownHoldsIncludingThisWindow"],
        "exposureLowerBound": value["ledgerLowerBoundIncludingThisHold"],
    }


def _r11_global_role_prefixes(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay pinned accounting records, never promote archived worker claims."""
    states: dict[str, dict[str, Any]] = {}
    for entry in entries:
        value = entry["source"]
        relative = entry["sourcePath"]
        if value["schemaVersion"] == "alk-r11-global-role-funding.v1":
            identity = _r11_role_funding_record(value, relative)
            digest = identity["fundingBatchSha256"]
            _require(digest not in states, "r11-role-prefix-history", "funding batch occurs twice")
            raw_sha = {
                name: hashlib.sha256(value[key].encode("utf-8")).hexdigest()
                for name, key in (
                    ("role-base.json", "baseRaw"),
                    ("role-inventory.json", "inventoryRaw"),
                    ("role-funding.json", "fundingRaw"),
                )
            }
            states[digest] = {
                "identity": identity,
                "contract": _r11_json(value["roleContractRaw"].encode("utf-8"), limit=131_072),
                "rawSha256": raw_sha,
                "raw": {},
                "prefixSha256": raw_sha.copy(),
                "steps": [],
            }
            continue
        key, record_raw = _r11_role_prefix_record(value, relative)
        digest = value["fundingBatchSha256"]
        _require(digest in states, "r11-role-prefix-history", "role record precedes or lacks its funded batch")
        state = states[digest]
        identity = state["identity"]
        count = len(state["raw"])
        roles = identity["inventory"]["roles"]
        _require(
            count < 2 * len(roles)
            and value["reviewId"] == identity["base"]["reviewId"]
            and key == roles[count // 2]["roleId"] + ("/reservation.json" if count % 2 == 0 else "/settlement.json")
            and value["previousCostPrefixSha256"] == canonical_digest(state["prefixSha256"])
            and key not in state["raw"],
            "r11-role-prefix-history",
            "role record skips, repeats, rebases or changes its immutable preceding prefix",
        )
        schema_raw = value["roleSubjectSchemaRaw"].encode("utf-8")
        _require(
            hashlib.sha256(schema_raw).hexdigest()
            == state["contract"]["runtimeSchemaByLayout"]["roleSubject"]["sha256"],
            "r11-role-prefix-schema",
            "role subject schema is not the funding contract snapshot",
        )
        basis = {
            "identity": identity,
            "schemas": {"roleSubject": _r11_json(schema_raw, limit=131_072)},
            "rawSha256": state["rawSha256"],
            "coordinatorProof": {
                "headSha256": entry["headSha256"],
                "head": {"unknownHolds": value["unknownHoldsIncludingThisWindow"]},
            },
        }
        state["raw"][key] = record_raw
        checked = _r11_role_cost_chain(Path("/"), value["reviewId"], basis, state["raw"], archived_workers=True)
        _require(
            checked["costChainSha256"] == value["costPrefixSha256"],
            "r11-role-prefix-history",
            "published role-prefix digest differs from reconstructed records",
        )
        state["prefixSha256"] = checked["prefixSha256"]
        state["steps"].append(
            {
                "headSha256": entry["headSha256"],
                "sourcePath": relative,
                "sourceSha256": canonical_digest(value),
                "costChainSha256": checked["costChainSha256"],
                "recordPath": key,
                "recordSha256": hashlib.sha256(record_raw).hexdigest(),
            }
        )
    return {
        digest: {
            "prefixSha256": state["prefixSha256"],
            "costChainSha256": canonical_digest(state["prefixSha256"]),
            "steps": state["steps"],
            "recordCount": len(state["raw"]),
            "workerEvidenceReadMode": "ARCHIVED_DIGESTS_ONLY",
        }
        for digest, state in states.items()
    }


def _r11_coordinator_source(primary: Path, relative: str) -> tuple[dict[str, Any], bytes]:
    if (
        isinstance(relative, str)
        and re.fullmatch(
            re.escape(_R11_COORDINATOR_BASE) + r"/role-prefixes/[0-9a-f]{64}/[0-9a-f]{64}/record\.json", relative
        )
        is not None
    ):
        raw = read_authority_bytes(primary / relative, root=primary, max_bytes=131_072)
        value = _r11_json(raw, limit=131_072)
        _r11_role_prefix_record(value, relative)
        _require(raw == canonical_bytes(value), "r11-role-prefix-record", "role-prefix source must be canonical")
        return value, raw
    if (
        isinstance(relative, str)
        and re.fullmatch(re.escape(_R11_COORDINATOR_BASE) + r"/role-funding/[0-9a-f]{64}/admission\.json", relative)
        is not None
    ):
        raw = read_authority_bytes(primary / relative, root=primary, max_bytes=131_072)
        value = _r11_json(raw, limit=131_072)
        _r11_role_funding_record(value, relative)
        _require(raw == canonical_bytes(value), "r11-role-funding-record", "funding archive must be canonical")
        return value, raw
    _require(
        isinstance(relative, str)
        and normalize_authority_path(relative) == relative
        and re.fullmatch(
            re.escape(_R11_COORDINATOR_BASE) + r"/r[1-9][0-9]*-[a-z0-9-]+/(admission|cost)\.json", relative
        )
        is not None,
        "r11-opening-origin",
        "bounded coordinator window source path required",
    )
    relative = _validated_cast(str, relative)
    raw = read_authority_bytes(primary / relative, root=primary, max_bytes=131_072)
    value = _r11_json(raw, limit=131_072)
    _require(
        value.get("schemaVersion") not in {"alk-r11-global-role-funding.v1", "alk-r11-global-role-prefix.v1"},
        "r11-role-funding-record",
        "role funding cannot masquerade as an ordinary window",
    )
    numeric = (
        "tokenCap",
        "protectedCloseoutTokens",
        "priorUnknownHolds",
        "unknownHoldsIncludingThisWindow",
        "priorLedgerLowerBound",
        "ledgerLowerBoundIncludingThisHold",
    )
    _require(
        value.get("status") in {"ADMITTED_PREAPPROVED_BY_USER", "UNAVAILABLE_FULL_HOLD_RETAINED"}
        and value.get("costStatus") == "UNAVAILABLE"
        and "actualTokens" in value
        and value["actualTokens"] is None
        and "actualInputTokens" in value
        and value["actualInputTokens"] is None
        and all(type(value.get(key)) is int and value[key] >= 0 for key in numeric)
        and 0 < value["protectedCloseoutTokens"] < value["tokenCap"] <= 300_000
        and value["priorUnknownHolds"] + value["tokenCap"] == value["unknownHoldsIncludingThisWindow"]
        and value["priorLedgerLowerBound"] + value["tokenCap"] == value["ledgerLowerBoundIncludingThisHold"]
        and value["priorLedgerLowerBound"] >= value["priorUnknownHolds"]
        and value.get("priorBudgetResumed") is False,
        "r11-opening-origin",
        "coordinator source does not preserve its full unknown hold",
    )
    _require(
        (Path(relative).name == "admission.json" and value["status"] == "ADMITTED_PREAPPROVED_BY_USER")
        or (
            Path(relative).name == "cost.json"
            and value["status"] == "UNAVAILABLE_FULL_HOLD_RETAINED"
            and type(value.get("priorUnknownHoldsReleased")) is int
            and value["priorUnknownHoldsReleased"] == 0
        ),
        "r11-opening-origin",
        "coordinator source stage/status differs",
    )
    return value, raw


def _r11_coordinator_head_bytes(primary: Path) -> bytes | None:
    path = primary / _R11_COORDINATOR_HEAD
    if not path.exists():
        _require(not path.is_symlink(), "r11-opening-origin", "coordinator head is indirect")
        return None
    return read_authority_bytes(path, root=primary, max_bytes=131_072)


def _r11_coordinator_transition(
    previous_path: str, previous: dict[str, Any], source_path: str, value: dict[str, Any], *, seed: bool = False
) -> None:
    """Check one declared coordinator edge; values must pass the source reader."""
    _require(type(seed) is bool, "r11-opening-transition", "explicit seed disposition required")
    previous_role = previous.get("schemaVersion") in {"alk-r11-global-role-funding.v1", "alk-r11-global-role-prefix.v1"}
    next_role = value.get("schemaVersion") in {"alk-r11-global-role-funding.v1", "alk-r11-global-role-prefix.v1"}
    if previous_role or next_role:
        cursor = previous["coordinatorCursor"] if previous_role else previous_path
        _require(
            not seed
            and (previous_role or Path(previous_path).name == "cost.json")
            and value["priorUnknownHolds"] == previous["unknownHoldsIncludingThisWindow"]
            and value["priorLedgerLowerBound"] == previous["ledgerLowerBoundIncludingThisHold"],
            "r11-role-funding-transition",
            "role funding must extend a settled coordinator balance exactly",
        )
        if next_role:
            _require(
                value["coordinatorCursor"] == cursor,
                "r11-role-funding-transition",
                "role funding changes its last closed coordinator window",
            )
        else:
            _require(
                Path(source_path).name == "admission.json"
                and int(Path(source_path).parent.name.split("-", 1)[0][1:])
                > int(Path(cursor).parent.name.split("-", 1)[0][1:]),
                "r11-role-funding-transition",
                "coordinator cannot close/replay an old window over role funding",
            )
        return
    if Path(source_path).parent == Path(previous_path).parent:
        _require(
            (seed and previous_path == source_path == _R11_COORDINATOR_SEED)
            or (not seed and Path(previous_path).name == "admission.json" and Path(source_path).name == "cost.json"),
            "r11-opening-transition",
            "only the pinned seed or one same-window close is permitted",
        )
        keys = (
            "tokenCap",
            "protectedCloseoutTokens",
            "priorUnknownHolds",
            "unknownHoldsIncludingThisWindow",
            "priorLedgerLowerBound",
            "ledgerLowerBoundIncludingThisHold",
        )
        _require(
            all(value[key] == previous[key] for key in keys),
            "r11-opening-transition",
            "closing a window cannot change its held balance",
        )
    else:
        old_number = int(Path(previous_path).parent.name.split("-", 1)[0][1:])
        new_number = int(Path(source_path).parent.name.split("-", 1)[0][1:])
        _require(
            not seed
            and Path(previous_path).name == "cost.json"
            and Path(source_path).name == "admission.json"
            and new_number > old_number
            and value["priorUnknownHolds"] == previous["unknownHoldsIncludingThisWindow"]
            and value["priorLedgerLowerBound"] == previous["ledgerLowerBoundIncludingThisHold"],
            "r11-opening-transition",
            "new window must extend the latest closed balance exactly",
        )


def _decode_coordinator_origin(
    head_raw: bytes, *, primary: Path, seed: dict[str, Any], observed: dict[Path, bytes]
) -> dict[str, Any]:
    head = _r11_json(head_raw, limit=131072)
    _require(
        set(head)
        == {
            "schemaVersion",
            "sourcePath",
            "sourceSha256",
            "previousHeadSha256",
            "seedSha256",
            "unknownHolds",
            "exposureLowerBound",
        }
        and head["schemaVersion"] == "alk-r11-coordinator-cost-head.v1"
        and (head["seedSha256"] == _R11_COORDINATOR_SEED_SHA)
        and (
            head["previousHeadSha256"] is None
            or (
                isinstance(head["previousHeadSha256"], str)
                and re.fullmatch("[0-9a-f]{64}", head["previousHeadSha256"]) is not None
            )
        ),
        "r11-opening-origin",
        "coordinator head shape or seed differs",
    )
    try:
        value, source_raw = _r11_coordinator_source(primary, head["sourcePath"])
    except OSError as exc:
        raise LifecycleError("r11-opening-origin", "coordinator source is unavailable") from exc
    _require(
        head["sourceSha256"] == hashlib.sha256(source_raw).hexdigest()
        and type(head["unknownHolds"]) is int
        and (type(head["exposureLowerBound"]) is int)
        and (
            head["unknownHolds"] == value["unknownHoldsIncludingThisWindow"] >= seed["unknownHoldsIncludingThisWindow"]
        )
        and (
            head["exposureLowerBound"]
            == value["ledgerLowerBoundIncludingThisHold"]
            >= seed["ledgerLowerBoundIncludingThisHold"]
        )
        and (observed.get(primary / head["sourcePath"], source_raw) == source_raw),
        "r11-opening-stale",
        "source/head differs or drops the pinned baseline",
    )
    if value.get("schemaVersion") == "alk-r11-global-role-funding.v1":
        funding = _r11_json(value["fundingRaw"].encode("utf-8"), limit=131072)
        _require(
            head["previousHeadSha256"] == funding["priorHeadSha256"],
            "r11-role-funding-transition",
            "funding is not joined to its exact preceding raw head",
        )
    if value.get("schemaVersion") == "alk-r11-global-role-prefix.v1":
        _require(
            head["previousHeadSha256"] == value["priorHeadSha256"],
            "r11-role-prefix-transition",
            "role prefix is not bound to its preceding raw global head",
        )
    observed[primary / head["sourcePath"]] = source_raw
    return {
        "schemaVersion": "alk-r11-coordinator-origin.v1",
        "status": "CURRENT_DECLARED_SOURCE_MATCHED",
        "primaryCheckout": str(primary),
        "head": head,
        "headSha256": hashlib.sha256(head_raw).hexdigest(),
        "source": value,
        "sourceRaw": source_raw,
        "headRaw": head_raw,
        "measurementQualified": False,
        "wholeHistoryComplete": False,
        "hardCapClaim": "DENY",
    }


def read_coordinator_cost_head(project_root: Path, *, ancestor_head_sha256: str | None = None) -> dict[str, Any]:
    """Read current declared provenance and optionally prove a pinned ancestor.

    Only the interval from that immutable opening to the current head is proved.
    Earlier completeness, measured spend and full-host enforcement stay denied.
    Missing, altered, cyclic, over-limit or pending ancestry never falls back to
    a current-balance comparison. This reads no session history or telemetry.
    """
    _require(
        ancestor_head_sha256 is None
        or (isinstance(ancestor_head_sha256, str) and re.fullmatch("[0-9a-f]{64}", ancestor_head_sha256) is not None),
        "r11-opening-ancestry",
        "ancestor must be an exact raw head digest",
    )
    primary = _r11_coordinator_root(Path(project_root).absolute())
    path = primary / _R11_COORDINATOR_HEAD
    pending = path.with_suffix(".pending.json")
    _require(
        not pending.exists() and not pending.is_symlink(),
        "r11-opening-pending",
        "coordinator head update is unresolved",
    )
    raw = _r11_coordinator_head_bytes(primary)
    _require(raw is not None, "r11-opening-origin", "coordinator head is not installed")
    seed, seed_raw = _r11_coordinator_source(primary, _R11_COORDINATOR_SEED)
    _require(
        hashlib.sha256(seed_raw).hexdigest() == _R11_COORDINATOR_SEED_SHA,
        "r11-opening-origin",
        "pinned coordinator seed differs",
    )
    observed = {primary / _R11_COORDINATOR_SEED: seed_raw}

    current = _decode_coordinator_origin(_validated_cast(bytes, raw), primary=primary, seed=seed, observed=observed)
    result = dict(current)
    if ancestor_head_sha256 is not None:
        chain = [current["headSha256"]]
        operations: set[str] = set()
        role_admissions, reviews, ledger_entries = [], set(), []

        def record_roles(item: dict[str, Any]) -> None:
            value = item["source"]
            if value.get("schemaVersion") in {"alk-r11-global-role-funding.v1", "alk-r11-global-role-prefix.v1"}:
                ledger_entries.append(
                    {"headSha256": item["headSha256"], "sourcePath": item["head"]["sourcePath"], "source": value}
                )
            if value.get("schemaVersion") != "alk-r11-global-role-funding.v1":
                return
            identity = _r11_role_funding_record(value, item["head"]["sourcePath"])
            ids = {row["operationId"] for row in identity["inventory"]["roles"]}
            review = identity["base"]["reviewId"]
            _require(
                not operations.intersection(ids) and review not in reviews,
                "r11-role-funding-reused",
                "a review or operation was funded twice in the pinned interval",
            )
            operations.update(ids)
            reviews.add(review)
            role_admissions.append(
                {
                    "headSha256": item["headSha256"],
                    "sourcePath": item["head"]["sourcePath"],
                    "sourceSha256": item["head"]["sourceSha256"],
                    "reviewId": review,
                    "fundingBatchSha256": identity["fundingBatchSha256"],
                    "operationIds": sorted(ids),
                    "openingHeadSha256": identity["base"]["openingHeadSha256"],
                }
            )

        record_roles(current)
        total = len(_validated_cast(bytes, raw)) + len(seed_raw) + len(current["sourceRaw"])
        while current["headSha256"] != ancestor_head_sha256:
            parent_sha = current["head"]["previousHeadSha256"]
            _require(
                parent_sha is not None and parent_sha not in chain and len(chain) < 4096,
                "r11-opening-ancestry",
                "opening is absent, cyclic or beyond the bounded chain",
            )
            archived = path.parent / "coordinator-cost-head-history" / (parent_sha + ".json")
            try:
                parent_raw = read_authority_bytes(archived, root=primary, max_bytes=131_072)
            except OSError as exc:
                raise LifecycleError("r11-opening-ancestry", "archived predecessor is unavailable") from exc
            _require(
                hashlib.sha256(parent_raw).hexdigest() == parent_sha,
                "r11-opening-ancestry",
                "archived predecessor differs from its raw digest",
            )
            parent = _decode_coordinator_origin(parent_raw, primary=primary, seed=seed, observed=observed)
            record_roles(parent)
            _r11_coordinator_transition(
                parent["head"]["sourcePath"], parent["source"], current["head"]["sourcePath"], current["source"]
            )
            total += len(parent_raw) + len(parent["sourceRaw"])
            _require(total <= 16_777_216, "r11-opening-ancestry", "opening proof exceeds bounded raw storage")
            observed[archived] = parent_raw
            chain.append(parent_sha)
            current = parent
        result.update(
            ancestor=current,
            ancestryHeadSha256s=chain,
            ancestryQualified=True,
            ancestryScope="PINNED_OPENING_TO_CURRENT_HEAD",
        )
        seed_head = canonical_digest(_r11_coordinator_head_value(_R11_COORDINATOR_SEED, seed_raw, seed, None))
        if ledger_entries and ancestor_head_sha256 == seed_head:
            result["roleLedgerEntries"] = list(reversed(ledger_entries))
            result["roleCostPrefixes"] = _r11_global_role_prefixes(result["roleLedgerEntries"])
        if role_admissions:
            if ancestor_head_sha256 == seed_head:
                _require(
                    all(
                        row["openingHeadSha256"] in chain
                        and chain.index(row["openingHeadSha256"]) > chain.index(row["headSha256"])
                        for row in role_admissions
                    ),
                    "r11-role-funding-origin",
                    "a funded review opening is not an earlier head of the pinned ledger",
                )
            result["roleFundingAdmissions"] = role_admissions
    try:
        stable = (
            _r11_coordinator_head_bytes(primary) == raw
            and all(read_authority_bytes(p, root=primary, max_bytes=131_072) == value for p, value in observed.items())
            and not pending.exists()
            and not pending.is_symlink()
        )
    except OSError:
        stable = False
    _require(stable, "r11-opening-stale", "coordinator head, source or ancestry changed during read")
    return result


def advance_coordinator_cost_head(project_root: Path, *, source_path: str) -> dict[str, Any]:
    """Publish one declared window advance or same-window close, with sticky failure.

    Controller bookkeeping, not a host attestation. No history is replayed and
    no partial/unknown spend is converted to measured usage or released.
    """
    primary = _r11_coordinator_root(Path(project_root).absolute())
    path = primary / _R11_COORDINATOR_HEAD
    previous_raw = _r11_coordinator_head_bytes(primary)
    if previous_raw is None:
        previous_path = _R11_COORDINATOR_SEED
        previous, raw = _r11_coordinator_source(primary, previous_path)
        _require(
            hashlib.sha256(raw).hexdigest() == _R11_COORDINATOR_SEED_SHA,
            "r11-opening-origin",
            "pinned coordinator opening seed differs",
        )
    else:
        current = read_coordinator_cost_head(project_root)
        _require(current["headRaw"] == previous_raw, "r11-opening-stale", "head changed before update")
        previous_path, previous = current["head"]["sourcePath"], current["source"]
    value, source_raw = _r11_coordinator_source(primary, source_path)
    if value.get("schemaVersion") == "alk-r11-global-role-funding.v1":
        identity = _r11_role_funding_record(value, source_path)
        seed_value, seed_raw = _r11_coordinator_source(primary, _R11_COORDINATOR_SEED)
        seed_head = canonical_digest(_r11_coordinator_head_value(_R11_COORDINATOR_SEED, seed_raw, seed_value, None))
        history = read_coordinator_cost_head(project_root, ancestor_head_sha256=seed_head)
        ids = {row["operationId"] for row in identity["inventory"]["roles"]}
        prior_rows = history.get("roleFundingAdmissions", [])
        _require(
            previous_raw is not None
            and history["headRaw"] == previous_raw
            and identity["funding"]["priorHeadSha256"] == history["headSha256"]
            and identity["base"]["openingHeadSha256"] in history["ancestryHeadSha256s"]
            and all(
                not ids.intersection(row["operationIds"]) and row["reviewId"] != identity["base"]["reviewId"]
                for row in prior_rows
            ),
            "r11-role-funding-reused",
            "stale prior head, absent opening or reused funded review/operation",
        )
    if value.get("schemaVersion") == "alk-r11-global-role-prefix.v1":
        seed_value, seed_raw = _r11_coordinator_source(primary, _R11_COORDINATOR_SEED)
        seed_head = canonical_digest(_r11_coordinator_head_value(_R11_COORDINATOR_SEED, seed_raw, seed_value, None))
        history = read_coordinator_cost_head(project_root, ancestor_head_sha256=seed_head)
        _require(
            previous_raw is not None
            and history["headRaw"] == previous_raw
            and value["priorHeadSha256"] == history["headSha256"],
            "r11-role-prefix-stale",
            "role-prefix predecessor changed before global commit",
        )
        proposed = _r11_coordinator_head_value(source_path, source_raw, value, history["headSha256"])
        _r11_global_role_prefixes(
            [
                *history.get("roleLedgerEntries", []),
                {"headSha256": canonical_digest(proposed), "sourcePath": source_path, "source": value},
            ]
        )
    _r11_coordinator_transition(
        previous_path, previous, source_path, value, seed=previous_raw is None and source_path == _R11_COORDINATOR_SEED
    )
    head = _r11_coordinator_head_value(
        source_path, source_raw, value, hashlib.sha256(previous_raw).hexdigest() if previous_raw is not None else None
    )
    # Direct existing authority directory; avoid changing permissions of prior artifacts.
    pending = path.with_suffix(".pending.json")
    temporary = path.with_suffix(".next.json")

    def exclusive(target: Path, raw: bytes) -> None:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    exclusive(pending, canonical_bytes(head))
    _sync_directory(path.parent)
    if (
        _r11_coordinator_head_bytes(primary) != previous_raw
        or read_authority_bytes(primary / source_path, root=primary, max_bytes=131_072) != source_raw
    ):
        # This writer has not touched the head. Release only its own stale claim;
        # a competing successful update must not be left blocked by this loser.
        pending.unlink()
        _sync_directory(path.parent)
        raise LifecycleError("r11-opening-stale", "source/head changed after update claim")
    if previous_raw is not None:
        archive = path.parent / "coordinator-cost-head-history"
        archive.mkdir(mode=0o700, exist_ok=True)
        _require(stat.S_ISDIR(archive.lstat().st_mode), "r11-opening-origin", "head archive is indirect")
        archived = archive / (hashlib.sha256(previous_raw).hexdigest() + ".json")
        if archived.exists():
            _require(
                read_authority_bytes(archived, root=primary, max_bytes=131_072) == previous_raw,
                "r11-opening-origin",
                "previous head archive differs",
            )
        else:
            exclusive(archived, previous_raw)
        _sync_directory(archive)
    exclusive(temporary, canonical_bytes(head))
    _sync_directory(path.parent)
    temporary.replace(path)
    _sync_directory(path.parent)
    pending.unlink()
    _sync_directory(path.parent)
    return read_coordinator_cost_head(project_root)


def _sync_directory(path: Path) -> None:
    _require(
        hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"),
        "r11-durable-storage-unavailable",
        "directory durability is unavailable on this route",
    )
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class DeclaredLedgerContext:
    """Verified legacy route values; a same-process constructor is not authority."""

    repository_root: Path
    primary_root: Path
    manifest_digest: str
    opening_ref: tuple[str, str, int]
    route_id: str = "release-2-16-declared-legacy-v1"


def resolve_declared_ledger_context(
    repository_root: Path,
    frozen_manifest: dict[str, Any],
    opening_ref: dict[str, Any],
) -> DeclaredLedgerContext:
    """Bind the reviewed legacy route to actual frozen inputs and primary Git root."""

    from agent_lifecycle.contracts.scoped_usage_schemas import (
        validate_source_ref_shape,
        validate_source_usage_policy_shape,
    )
    from agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity

    root = Path(repository_root).absolute()
    _require(
        frozen_manifest.get("status") == "FROZEN" and frozen_manifest.get("package", {}).get("id") == "release-2-16",
        "declared-ledger-route-unsupported",
        "only the registered release 2.16 route is supported",
    )
    runtime = frozen_manifest.get("runtimePolicy", {})
    policy = validate_source_usage_policy_shape(runtime.get("sourceUsageCompletion"))
    validate_source_ref_shape(opening_ref)
    _require(
        policy["openingRef"] == opening_ref,
        "declared-ledger-opening-mismatch",
        "opening must be independently selected by the frozen policy",
    )
    folder = Path(normalize_authority_path(opening_ref["path"])).parent
    manifest = _r11_json(
        read_authority_bytes(root / folder / "plan.manifest.json", root=root, max_bytes=1_048_576), limit=1_048_576
    )
    lock = _r11_json(
        read_authority_bytes(root / folder / "plan.lock.json", root=root, max_bytes=1_048_576), limit=1_048_576
    )
    _require(
        canonical_digest(manifest) == canonical_digest(frozen_manifest),
        "declared-ledger-manifest-mismatch",
        "caller manifest differs from actual frozen bytes",
    )
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    _require(
        opening_ref in lock["entries"],
        "declared-ledger-opening-mismatch",
        "opening is outside the exact frozen inventory",
    )
    opening_raw = read_authority_bytes(root / opening_ref["path"], root=root, max_bytes=65_536)
    _require(
        len(opening_raw) == opening_ref["bytes"] and hashlib.sha256(opening_raw).hexdigest() == opening_ref["sha256"],
        "declared-ledger-opening-mismatch",
        "opening bytes differ from their frozen reference",
    )
    opening = _r11_json(opening_raw, limit=65_536)
    _require(
        opening.get("schemaVersion") == "alk-r11-coordinator-cost-head.v1"
        and opening.get("seedSha256") == _R11_COORDINATOR_SEED_SHA,
        "declared-ledger-route-unsupported",
        "opening does not belong to the preserved legacy seed",
    )
    primary = _r11_coordinator_root(root)
    _, seed_raw = _r11_coordinator_source(primary, _R11_COORDINATOR_SEED)
    _require(
        hashlib.sha256(seed_raw).hexdigest() == _R11_COORDINATOR_SEED_SHA,
        "r11-opening-origin",
        "original financial seed bytes differ",
    )
    return DeclaredLedgerContext(
        root, primary, canonical_digest(manifest), (opening_ref["path"], opening_ref["sha256"], opening_ref["bytes"])
    )


def _require_declared_context(context: DeclaredLedgerContext) -> None:
    _require(
        isinstance(context, DeclaredLedgerContext) and context.route_id == "release-2-16-declared-legacy-v1",
        "declared-ledger-context-required",
        "registered verified legacy context is required",
    )


def read_declared_ledger(
    context: DeclaredLedgerContext,
    *,
    ancestor_head_sha256: str | None = None,
) -> dict[str, Any]:
    """Read the unchanged complete legacy head chain with original A/B guards."""

    _require_declared_context(context)
    result = read_coordinator_cost_head(context.repository_root, ancestor_head_sha256=ancestor_head_sha256)
    _require(
        Path(result["primaryCheckout"]) == context.primary_root,
        "r11-opening-origin",
        "primary Git identity differs from the selected context",
    )
    return result


def advance_declared_ledger(context: DeclaredLedgerContext, source_path: str) -> dict[str, Any]:
    """Keep exact legacy locking, ancestry, raw hashes and monotonic full holds."""

    _require_declared_context(context)
    _require(
        _r11_coordinator_root(context.repository_root) == context.primary_root,
        "r11-opening-origin",
        "primary Git identity differs from the selected context",
    )
    return advance_coordinator_cost_head(context.repository_root, source_path=source_path)


def read_declared_source(
    context: DeclaredLedgerContext,
    head: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    """Decode one original head source; the caller verifies its exact head digest."""

    _require_declared_context(context)
    return _r11_coordinator_source(context.primary_root, head["sourcePath"])
