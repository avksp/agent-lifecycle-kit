"""Registered legacy declared-accounting filesystem and worker archive reads. No host dispatch."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger_records import (
    _r11_cost_reservation,
    _r11_transport_binding,
    _require,
)
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import normalize_authority_path, read_authority_bytes
from agent_lifecycle.contracts.bounded_json import load_bounded_json as _r11_json

_MAX_REQUEST_BYTES = 131_072


def _read_private(
    path: Path,
    *,
    root: Path,
    allowed_modes: tuple[int, ...] = (0o600,),
    max_bytes: int = _MAX_REQUEST_BYTES,
) -> bytes:
    if os.name == "nt":
        from agent_lifecycle.contracts.private_storage import read_private_bytes

        try:
            return read_private_bytes(path, root=root, modes=allowed_modes, max_bytes=max_bytes)
        except LifecycleError as exc:
            raise LifecycleError("codex-exact-private-path-unsafe", exc.message) from exc
    if not path.is_relative_to(root):
        raise LifecycleError("codex-exact-private-path-unsafe", "private artifact lies outside root")
    current = path.parent
    while current != root:
        info = current.lstat()
        relative = current.relative_to(root).parts
        shared_parent = relative in {("work",), ("work", "release-2-16"), ("work", "release-2-16", "evidence")}
        if not stat.S_ISDIR(info.st_mode) or (not shared_parent and stat.S_IMODE(info.st_mode) != 0o700):
            raise LifecycleError("codex-exact-private-path-unsafe", "private parent is not mode 0700")
        current = current.parent
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in allowed_modes or info.st_size > max_bytes:
        raise LifecycleError("codex-exact-private-path-unsafe", "private file has unsafe mode, type or size")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())

        def identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
            return (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns)

        if identity(opened) != identity(info):
            raise LifecycleError("codex-exact-private-path-unsafe", "private file changed before reading")
        raw = stream.read(max_bytes + 1)
        if identity(os.fstat(stream.fileno())) != identity(opened):
            raise LifecycleError("codex-exact-private-path-unsafe", "private file changed while reading")
    if len(raw) > max_bytes:
        raise LifecycleError("codex-exact-private-overflow", "private artifact exceeds byte limit")
    return raw


def _r11_git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            timeout=15,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("r11-source-unavailable", "cannot read current Git inventory") from exc
    _require(
        result.returncode == 0 and len(result.stdout) <= 8_388_608 and len(result.stderr) <= 65_536,
        "r11-source-unavailable",
        "Git inventory read failed or exceeded its bound",
    )
    return result.stdout


_R11_VALIDATION_ROOTS = ("src", "tests", "policy", "tools", "profiles", "tasks/release-2-16")


def capture_review_validation_sources(project_root: Path) -> dict[str, str]:
    """Capture all local validation inputs, including imported helpers and policy.

    The execution producer records this digest before/after each command and
    discovery. The collector recomputes it; a test-file-only receipt is stale.
    Generated Python caches are excluded, symlinks and special files refused.
    """
    root = Path(project_root).absolute()
    result: dict[str, str] = {}
    total = 0

    def walk_error(error: OSError) -> None:
        raise LifecycleError("r11-validation-source", "validation source directory cannot be read") from error

    for relative in _R11_VALIDATION_ROOTS:
        base = root / relative
        _require(
            stat.S_ISDIR(base.lstat().st_mode), "r11-validation-source", "validation source root is missing or indirect"
        )
        for directory, dirs, files in os.walk(base, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(name for name in dirs if name != "__pycache__")
            for name in dirs:
                _require(
                    stat.S_ISDIR((Path(directory) / name).lstat().st_mode),
                    "r11-validation-source",
                    "validation source directory is indirect",
                )
            for name in sorted(files):
                if name.endswith((".pyc", ".pyo")):
                    continue
                path = Path(directory) / name
                raw = read_authority_bytes(path, root=root, max_bytes=8_388_608)
                total += len(raw)
                result[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
                _require(
                    len(result) <= 4096 and total <= 67_108_864,
                    "r11-validation-source",
                    "validation source inventory exceeds bound",
                )
    return dict(sorted(result.items()))


_R11_REVIEW_ROOT = "work/release-2-16/evidence/route-bootstrap"


def _r11_review_private(root: Path, path: Path) -> bytes:

    try:
        return _read_private(path, root=root)
    except OSError as exc:
        raise LifecycleError(
            "r11-review-evidence-unavailable", "assigned private review evidence is unavailable"
        ) from exc


def _r11_worker_directory(root: Path, binding: dict[str, str]) -> Path:
    _r11_transport_binding(binding)
    return root / _R11_REVIEW_ROOT / "shards" / binding["shardId"] / "worker"


def _r11_worker_sources(root: Path, worker_path: Path, instruction_path: Path) -> dict[str, str]:
    """Capture actual program/input and all ALK source dependencies, without execution."""
    worker = read_authority_bytes(worker_path, root=root, max_bytes=1_048_576)
    instruction = _r11_review_private(root, instruction_path)
    _r11_json(instruction, limit=131_072)
    executable = Path(sys.executable).resolve(strict=True)
    return {
        "workerSha256": hashlib.sha256(worker).hexdigest(),
        "instructionSha256": hashlib.sha256(instruction).hexdigest(),
        "pythonSha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "validationSourcesSha256": canonical_digest(capture_review_validation_sources(root)),
    }


def _r11_worker_disposition(
    result: dict[str, Any], reservation: dict[str, Any], finished_ns: int, source_stable: bool
) -> str:
    from agent_lifecycle.contracts.process_execution_schemas import validate_process_execution_receipt

    if result.get("processStarted") is False:
        return "NO_START"
    receipt = result.get("processReceipt")
    if not (
        result.get("processStarted") is True
        and result.get("status") == "PASS"
        and type(result.get("exitCode")) is int
        and result["exitCode"] == 0
        and result.get("timedOut") is False
        and result.get("cancelled") is False
        and result.get("outputLimitExceeded") is False
        and result.get("blockers") == []
        and result.get("observerDisposition") == "NOT_REQUESTED"
        and isinstance(receipt, dict)
        and type(result.get("deadlineMonotonicNs")) is int
        and 0 < finished_ns <= result["deadlineMonotonicNs"]
        and source_stable
    ):
        return "WORKER_FAILED" if result.get("processStarted") is True else "START_UNCERTAIN"
    cleanup = result.get("cleanup", {})
    if not (
        cleanup.get("status") == "PASS"
        and cleanup.get("directChildExited") is True
        and cleanup.get("knownDescendantsGone") is True
        and receipt.get("status") == "PASS"
        and receipt.get("exitCode") == 0
        and receipt.get("timedOut") is False
        and receipt.get("cancelled") is False
        and receipt.get("cleanup") == cleanup
        and receipt.get("commandIdentityHash") == reservation["commandIdentityHash"]
        and receipt.get("operationId") == reservation["binding"]["operationId"]
        and receipt.get("attemptId") == reservation["binding"]["shardId"]
        and receipt.get("adapterId") == "alk-r11-review-worker"
        and receipt.get("limits", {}).get("timeoutSeconds") == reservation["timeoutSeconds"]
        and receipt.get("limits", {}).get("maxOutputBytes") == 8192
        and isinstance(receipt.get("processIdentityHash"), str)
        and re.fullmatch("[0-9a-f]{64}", receipt["processIdentityHash"]) is not None
    ):
        return "WORKER_FAILED"
    if "absoluteDeadlineMonotonicNs" in reservation:
        original = reservation["absoluteDeadlineMonotonicNs"]
        start = result.get("startedMonotonicNs")
        if not (
            type(original) is int
            and type(start) is int
            and 0 < start < original
            and result.get("absoluteDeadlineMonotonicNs") == original
            and result["deadlineMonotonicNs"] == min(original, start + reservation["timeoutSeconds"] * 1_000_000_000)
        ):
            return "WORKER_FAILED"
    if validate_process_execution_receipt(receipt).get("status") != "PASS":
        return "WORKER_FAILED"
    return "WORKER_PROCESS_FINISHED"


def read_source_review_worker(project_root: Path, *, binding: dict[str, str]) -> dict[str, Any]:
    """Reopen a durable worker outcome; late output never upgrades a failure."""
    root = Path(project_root).absolute()
    directory = _r11_worker_directory(root, binding)
    try:
        _r11_review_private(root, directory / "reservation.json")
        _require(
            {path.name for path in directory.iterdir()} == {"reservation.json", "process-result.json", "terminal.json"},
            "r11-worker-uncertain",
            "worker publication is missing, pending or conflicted",
        )
        raw = {
            name: _r11_review_private(root, directory / name)
            for name in ("reservation.json", "process-result.json", "terminal.json")
        }
        reservation, result, terminal = (
            _r11_json(raw[name], limit=131_072) for name in ("reservation.json", "process-result.json", "terminal.json")
        )
        _require(
            reservation.get("schemaVersion") == "alk-r11-worker-reservation.v1"
            and terminal.get("schemaVersion") == "alk-r11-worker-terminal.v1"
            and reservation.get("binding") == terminal.get("binding") == binding
            and terminal.get("reservationSha256") == hashlib.sha256(raw["reservation.json"]).hexdigest()
            and terminal.get("processResultSha256") == hashlib.sha256(raw["process-result.json"]).hexdigest()
            and type(terminal.get("finishedMonotonicNs")) is int
            and type(terminal.get("sourceStableAtCompletion")) is bool
            and terminal.get("status")
            == _r11_worker_disposition(
                result, reservation, terminal["finishedMonotonicNs"], terminal["sourceStableAtCompletion"]
            )
            and terminal.get("costStatus") == reservation.get("costStatus") == "UNAVAILABLE"
            and "actualModelTokens" in terminal
            and "actualModelTokens" in reservation
            and terminal["actualModelTokens"] is None
            and reservation["actualModelTokens"] is None
            and type(reservation.get("heldUnknownTokens")) is int
            and reservation["heldUnknownTokens"] > 0
            and terminal.get("heldUnknownTokens") == reservation["heldUnknownTokens"]
            and terminal.get("processMayHaveStarted") is (result.get("processStarted") is not False)
            and terminal.get("hostModelStart") == "UNPROVEN"
            and all(
                terminal.get(key) is False
                for key in ("producerQualified", "retryAuthorized", "firstNativeBootstrapEligible")
            ),
            "r11-worker-identity",
            "worker result, cost hold or reserved identity differs",
        )
        if terminal["status"] == "WORKER_PROCESS_FINISHED":
            worker = root / normalize_authority_path(reservation["workerPath"])
            instruction = root / normalize_authority_path(reservation["instructionPath"])
            _require(
                _r11_worker_sources(root, worker, instruction) == reservation["sourceSha256"],
                "r11-worker-source-stale",
                "positive worker evidence no longer matches current source/input",
            )
        _require(
            {path.name for path in directory.iterdir()} == set(raw)
            and all(_r11_review_private(root, directory / name) == value for name, value in raw.items()),
            "r11-worker-uncertain",
            "worker result changed during read",
        )
        return terminal
    except OSError as exc:
        raise LifecycleError("r11-worker-uncertain", "worker outcome is unavailable") from exc


def _r11_cost_worker(
    root: Path, binding: dict[str, str], held: int, *, review_id: str, cost_chain_sha: str, request_sha: str
) -> dict[str, Any]:
    _require(binding["threadId"] != "U" * 256, "r11-v5-runtime-retired", "cost outcome requires an actual role thread")
    directory = _r11_worker_directory(root, binding)
    allowed = {
        "reservation.json",
        "dispatch.pending.json",
        "process-result.json",
        "terminal.pending.json",
        "terminal.json",
    }
    raw = {}
    if directory.exists():
        _require(stat.S_ISDIR(directory.lstat().st_mode), "r11-cost-worker", "worker directory is indirect")
        names = {path.name for path in directory.iterdir()}
        _require(names <= allowed, "r11-cost-worker", "unrecognized worker evidence")
        raw = {name: _r11_review_private(root, directory / name) for name in sorted(names)}
    else:
        _require(not directory.is_symlink(), "r11-cost-worker", "worker directory is indirect")
    try:
        terminal = read_source_review_worker(root, binding=binding)
    except (LifecycleError, OSError, ValueError, KeyError, TypeError):
        terminal = None
    if terminal is not None:
        reservation = _r11_json(raw["reservation.json"], limit=131_072)
        _require(
            terminal["heldUnknownTokens"] == held
            and reservation.get("costReviewId") == review_id
            and reservation.get("costChainSha256") == cost_chain_sha
            and reservation.get("requestSha256") == request_sha,
            "r11-cost-worker",
            "worker differs from the admitted cumulative hold, chain or request",
        )
    result = {
        "state": terminal["status"] if terminal is not None else "START_UNCERTAIN",
        "evidenceSha256": {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
    }
    return result


def _r11_role_cost_chain(
    root: Path, review_id: str, basis: dict[str, Any], raw: dict[str, bytes], *, archived_workers: bool = False
) -> dict[str, Any]:
    """Reopen declared role prefixes; this cannot establish batch admission.

    Canonical ancestors alone do not prove exclusive global funding, first-hold
    reuse, source/support freshness, template fit or accepted SHARED evidence.
    The public reader therefore never promotes this match into a start grant.
    """
    _require(type(archived_workers) is bool, "r11-role-cost-mode", "explicit worker evidence mode required")
    identity = basis["identity"]
    funding = identity["funding"]
    prefixes = dict(basis["rawSha256"])
    reservations: list[dict] = []
    settlements: list[dict] = []
    threads = set()
    previous = None
    for index, role in enumerate(identity["inventory"]["roles"]):
        name = role["roleId"]
        key = name + "/reservation.json"
        if key not in raw:
            break
        value = _r11_json(raw[key], limit=131_072)
        fields = ("binding", "requestSha256", "sharedEvidenceSha256", "reservedAtUtc", "absoluteDeadlineUtc")
        _require(all(field in value for field in fields), "r11-role-cost-reservation", "dispatch fields missing")
        expected = _r11_cost_reservation(
            basis, index, previous, dispatch={field: value[field] for field in fields}, prefix=prefixes
        )
        _require(
            raw[key] == canonical_bytes(expected)
            and expected["binding"]["threadId"] not in threads
            and (
                index == 0
                or (
                    len(settlements) == index
                    and settlements[-1]["worker"]["state"] == "WORKER_PROCESS_FINISHED"
                    and datetime.fromisoformat(expected["reservedAtUtc"].replace("Z", "+00:00"))
                    >= datetime.fromisoformat(reservations[-1]["reservedAtUtc"].replace("Z", "+00:00"))
                )
            ),
            "r11-role-cost-prefix",
            "reservation rebases, reuses, skips, changes hold or follows failed work",
        )
        threads.add(expected["binding"]["threadId"])
        reservations.append(expected)
        prefixes[key] = hashlib.sha256(raw[key]).hexdigest()
        settlement_key = name + "/settlement.json"
        if settlement_key not in raw:
            break
        if archived_workers:
            worker = _r11_json(raw[settlement_key], limit=131_072).get("worker")
            _require(
                isinstance(worker, dict)
                and set(worker) == {"state", "evidenceSha256"}
                and isinstance(worker["state"], str)
                and worker["state"] in {"NO_START", "START_UNCERTAIN", "WORKER_FAILED", "WORKER_PROCESS_FINISHED"}
                and isinstance(worker["evidenceSha256"], dict)
                and set(worker["evidenceSha256"])
                <= {
                    "reservation.json",
                    "dispatch.pending.json",
                    "process-result.json",
                    "terminal.pending.json",
                    "terminal.json",
                }
                and all(
                    isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest) is not None
                    for digest in worker["evidenceSha256"].values()
                ),
                "r11-role-cost-worker",
                "archived worker digest record is invalid; not live worker proof",
            )
            worker = _validated_cast(dict[str, Any], worker)
        else:
            worker = _r11_cost_worker(
                root,
                expected["binding"],
                funding["admittedUnknownHolds"],
                review_id=review_id,
                cost_chain_sha=canonical_digest(prefixes),
                request_sha=expected["requestSha256"],
            )
        settlement = {
            "schemaVersion": "alk-r11-role-cost-settlement.v1",
            "reviewId": review_id,
            "binding": expected["binding"],
            "reservationSha256": hashlib.sha256(raw[key]).hexdigest(),
            "previousCostPrefixSha256": canonical_digest(prefixes),
            "worker": worker,
            "costStatus": "UNAVAILABLE",
            "actualModelTokens": None,
            "releasedUnknownTokens": 0,
            "heldUnknownTokens": funding["admittedUnknownHolds"],
            "accountedExposureLowerBound": funding["admittedExposureLowerBound"],
            "retryAuthorized": False,
            "hardCapClaim": "DENY",
        }
        _require(
            raw[settlement_key] == canonical_bytes(settlement),
            "r11-role-cost-settlement",
            "settlement changes raw worker, prefix, full hold or unknown usage",
        )
        settlements.append(settlement)
        previous = raw[settlement_key]
        prefixes[settlement_key] = hashlib.sha256(previous).hexdigest()
    _require(
        len(raw) == len(reservations) + len(settlements),
        "r11-role-cost-prefix",
        "unassigned, skipped or unsettled cost prefix; replay refused",
    )
    return {
        "schemaVersion": "alk-r11-role-cost-chain.v1",
        "status": "ROLE_COST_PREFIX_MATCHED_NOT_ADMITTED",
        "baseSha256": identity["baseSha256"],
        "roleInventorySha256": identity["roleInventorySha256"],
        "fundingBatchSha256": identity["fundingBatchSha256"],
        "costChainSha256": canonical_digest(prefixes),
        "prefixSha256": prefixes,
        "reservations": reservations,
        "settlements": settlements,
        "workerEvidenceReadMode": "ARCHIVED_DIGESTS_ONLY" if archived_workers else "CURRENT_PRIVATE_FILES",
        "unreservedRoleIds": [role["roleId"] for role in identity["inventory"]["roles"][len(reservations) :]],
        "allRolesSettled": len(settlements) == len(identity["inventory"]["roles"]),
        "declaredUnknownHoldsAtFunding": funding["admittedUnknownHolds"],
        "declaredExposureAtFunding": funding["admittedExposureLowerBound"],
        "currentCoordinatorHeadSha256": basis["coordinatorProof"]["headSha256"],
        "currentCoordinatorUnknownHolds": basis["coordinatorProof"]["head"]["unknownHolds"],
        "costStatus": "UNAVAILABLE",
        "actualModelTokens": None,
        "releasedUnknownTokens": 0,
        "fundingAdmitted": False,
        "sharedEvidenceAccepted": False,
        "producerQualified": False,
        "retryAuthorized": False,
        "hardCapClaim": "DENY",
        "firstNativeBootstrapEligible": False,
    }


def _r11_coordinator_root(root: Path) -> Path:
    """Resolve this checkout's primary worktree, never a caller-selected ledger."""
    raw = _r11_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = Path(raw.decode("utf-8").strip())
    _require(
        common.is_absolute()
        and common.name == ".git"
        and stat.S_ISDIR(common.lstat().st_mode)
        and common.resolve(strict=True) == common,
        "r11-opening-origin",
        "standard direct primary Git directory required",
    )
    primary = common.parent
    _require(
        _r11_git(primary, "rev-parse", "--path-format=absolute", "--git-common-dir") == raw,
        "r11-opening-origin",
        "primary checkout Git identity differs",
    )
    return primary
