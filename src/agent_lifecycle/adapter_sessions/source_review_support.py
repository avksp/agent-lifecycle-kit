"""Owned source review support helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger import _sync_directory
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _R11_REVIEW_ROOT,
    _r11_review_private,
    capture_review_validation_sources,
)
from agent_lifecycle.accounting.declared_ledger_records import _require
from agent_lifecycle.adapter_sessions.attempt_authority import _write
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_SUPPORT_ORACLE_SHA256,
    _r11_fresh_start,
    _r11_notification_envelope,
    _r11_role_material_authority,
    _r11_utc,
    _r11_wip,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import _r11_source_inputs
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import normalize_authority_path, read_authority_bytes
from agent_lifecycle.contracts.bounded_json import load_bounded_json as _r11_json
from agent_lifecycle.contracts.bounded_json import matches_closed_schema as _r11_role_schema_matches


class _TranscriptReceiver(Protocol):
    def receive(self, raw: bytes) -> None: ...


def _r11_support_authority(root: Path, *, role_delivery: bool = False) -> tuple[dict, dict, dict, dict[str, str]]:
    _require(type(role_delivery) is bool, "r11-support-authority", "explicit delivery version required")
    if role_delivery:
        current = _r11_role_material_authority(root)
        return (current["supportOracle"], current["expectedWip"], current["route"], current["authoritySha256"])
    _, expected, authority = _r11_source_inputs(root)
    prefix = "tasks/release-2-16/"
    lock = _r11_json(
        read_authority_bytes(root / (prefix + "plan.lock.json"), root=root, max_bytes=2_097_152), limit=2_097_152
    )
    entries = {row["path"]: row for row in lock["entries"]}
    docs = {}
    for name in (
        "SUPPORT-MEMBERSHIP-ORACLE-v4.json",
        "REQUIRED-PRIVATE-SUPPORT-v1.json",
        "route-bootstrap-contract.json",
    ):
        relative = prefix + name
        raw = read_authority_bytes(root / relative, root=root, max_bytes=262_144)
        digest = hashlib.sha256(raw).hexdigest()
        _require(
            entries.get(relative, {}).get("sha256") == digest and entries[relative]["bytes"] == len(raw),
            "r11-support-authority",
            "support contract is not bound to the installed lock",
        )
        authority[relative] = digest
        docs[name] = _r11_json(raw, limit=262_144)
    oracle, membership, route = (
        docs[name]
        for name in (
            "SUPPORT-MEMBERSHIP-ORACLE-v4.json",
            "REQUIRED-PRIVATE-SUPPORT-v1.json",
            "route-bootstrap-contract.json",
        )
    )
    _require(
        authority[prefix + "SUPPORT-MEMBERSHIP-ORACLE-v4.json"]
        == _R11_SUPPORT_ORACLE_SHA256
        == route["auditJoin"]["delivery"]["supportOracleSha256"]
        and authority[prefix + "REQUIRED-PRIVATE-SUPPORT-v1.json"] == oracle["requiredPrivateSupportMembershipSha256"]
        and membership["requiredKeys"] == oracle["requiredPrivateSupportKeys"]
        and len(set(membership["requiredKeys"])) == membership["requiredCount"] == 14
        and oracle["expectedAllProductPaths"] == expected["allProductPaths"]
        and oracle["expectedTemporaryLeadPaths"] == expected["temporaryLeadPaths"],
        "r11-support-authority",
        "support membership or oracle differs",
    )
    return oracle, expected, route, authority


def _r11_private_support(root: Path, directory: Path, names: list[str]) -> dict[str, bytes]:
    from .private_input import _read_private

    relative = directory.relative_to(root).as_posix() if directory.is_relative_to(root) else ""
    _require(
        relative.startswith("work/release-2-16/evidence/route-bootstrap/")
        and normalize_authority_path(relative) == relative
        and directory.name == "support",
        "r11-support-path",
        "support must be a dedicated bootstrap private directory",
    )
    try:
        # Check no-follow private ancestry before enumerating any supplied directory.
        first = _read_private(directory / names[0], root=root)
        _require(
            {p.name for p in directory.iterdir()} == set(names),
            "r11-support-membership",
            "private support has missing or extra members",
        )
        raw = {name: _read_private(directory / name, root=root) for name in names}
        _require(
            raw[names[0]] == first and {p.name for p in directory.iterdir()} == set(names),
            "r11-support-stale",
            "private support changed during read",
        )
    except OSError as exc:
        raise LifecycleError("r11-support-unavailable", "private support cannot be reopened") from exc
    return raw


def _r11_observe_test_rosters(root: Path, oracle: dict) -> dict[str, Any]:
    """Use the current supported interpreter, never execute a receipt-supplied path.

    A separate process avoids accepting modules cached from a different checkout.
    TestLoader discovers cases only; no test method is executed.
    """
    _require(sys.version_info >= (3, 11), "r11-validation-python", "supported Python is required")
    modules = {key: oracle["testBlocks"][key]["modules"] for key in ("C34", "C35")}
    script = """import json,pathlib,sys,unittest
root=pathlib.Path.cwd()
commands=json.loads(sys.argv[1])
result={}
for command,modules in commands.items():
 loader=unittest.TestLoader()
 suite=loader.loadTestsFromNames(modules)
 if loader.errors: raise RuntimeError('test discovery failed')
 def flatten(group):
  for item in group:
   if isinstance(item,unittest.TestSuite): yield from flatten(item)
   else: yield item.id()
 ids=list(flatten(suite))
 for module in modules:
  if pathlib.Path(sys.modules[module].__file__).resolve()!=root/(module.replace('.','/')+'.py'):
   raise RuntimeError('test module outside current checkout')
 if len(ids)!=len(set(ids)): raise RuntimeError('duplicate test IDs')
 result[command]=sorted(ids)
print(json.dumps({'rosters':result,'pythonResolvedPath':str(pathlib.Path(sys.executable).resolve()),'pythonVersion':list(sys.version_info[:3])}))
"""
    try:
        run = subprocess.run(
            [sys.executable, "-B", "-c", script, json.dumps(modules)],
            cwd=root,
            env={**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("r11-validation-discovery", "current loader discovery unavailable") from exc
    _require(
        run.returncode == 0 and len(run.stdout) <= 131_072 and not run.stderr,
        "r11-validation-discovery",
        "current loader discovery failed or emitted ambiguous output",
    )
    observed = _r11_json(run.stdout, limit=131_072)
    binary = Path(sys.executable).resolve(strict=True)
    _require(
        observed.get("pythonResolvedPath") == str(binary)
        and observed.get("pythonVersion") == list(sys.version_info[:3]),
        "r11-validation-python",
        "discovery interpreter differs",
    )
    observed["pythonSha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    return observed


def _r11_match_test_support(
    root: Path,
    command_id: str,
    raw: dict[str, bytes],
    oracle: dict,
    contract: dict,
    sources: dict[str, str],
    observed: dict[str, Any],
) -> dict[str, Any]:
    from .codex_source_subject import _r69h_expand_test_support

    ident = command_id.lower()
    execution, cases, result = (
        _r11_json(raw[f"{ident}-{suffix}.json"], limit=131_072) for suffix in ("execution", "cases", "result")
    )
    discovery = cases.get("loaderDiscoveryReceipt")
    _require(isinstance(discovery, dict), "r11-validation-discovery", "separate discovery receipt missing")
    discovery = _validated_cast(dict[str, Any], discovery)
    rule = oracle["testBlocks"][command_id]
    names = sorted(rule["baselineCaseIds"] + rule["reviewedPriorAdditionCaseIds"] + rule["r11RequiredCaseIds"])
    commands = [c for c in contract["validation"]["commands"] if c["id"] == command_id]
    _require(
        len(commands) == 1 and len(names) == len(set(names)) and observed.get("rosters", {}).get(command_id) == names,
        "r11-validation-roster",
        "current loader differs from the exact reviewed case roster",
    )
    command = commands[0]
    parts = shlex.split(command["command"])
    _require(
        command["command"] == rule["contractCommand"]
        and canonical_digest(command["command"]) == command["canonicalDigest"] == rule["commandDigest"]
        and parts
        == ["PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=src", "python3", "-m", "unittest", *rule["modules"], "-q"],
        "r11-validation-command",
        "locked validation command differs",
    )
    paths = [module.replace(".", "/") + ".py" for module in rule["modules"]]
    _require(all(path in sources for path in paths), "r11-validation-source", "test module source missing")
    test_sources = {path: sources[path] for path in paths}
    source_digest = canonical_digest(sources)
    _require(
        execution.get("source") == "SUBPROCESS_CAPTURE"
        and execution.get("contractCommand") == command["command"]
        and execution.get("commandDigest") == command["canonicalDigest"]
        and execution.get("argv") == parts[2:]
        and execution.get("cwd") == str(root)
        and execution.get("environment") == {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "src"}
        and type(execution.get("exitCode")) is int
        and execution["exitCode"] == 0
        and type(execution.get("processId")) is int
        and execution["processId"] > 0
        and execution.get("pythonResolvedPath") == observed["pythonResolvedPath"]
        and execution.get("pythonSha256") == observed["pythonSha256"]
        and execution.get("pythonVersion") == observed["pythonVersion"]
        and execution.get("testNames") == cases.get("testNames") == names
        and cases.get("commandId") == command_id
        and execution.get("sourceTestFileSha256") == cases.get("sourceTestFileSha256") == test_sources
        and discovery.get("sourceFileSha256")
        == discovery.get("sourceBeforeSha256")
        == discovery.get("sourceAfterSha256")
        == test_sources
        and discovery.get("discoveredCaseIds") == names
        and type(discovery.get("discoveredCaseCount")) is int
        and discovery["discoveredCaseCount"] == len(names)
        and discovery.get("moduleNames") == rule["modules"]
        and discovery.get("discoveryMethod") == "unittest.TestLoader.loadTestsFromNames"
        and all(
            receipt.get(key) == source_digest
            for receipt in (execution, discovery)
            for key in ("validationSourcesBeforeSha256", "validationSourcesAfterSha256")
        ),
        "r11-validation-source",
        "execution/discovery source, interpreter, command or identity differs",
    )
    _require(
        _r11_utc(execution.get("startedAtUtc"))
        <= _r11_utc(execution.get("endedAtUtc"))
        < _r11_utc(discovery.get("discoveryStartedAtUtc"))
        <= _r11_utc(discovery.get("discoveryEndedAtUtc"))
        <= datetime.now().astimezone(),
        "r11-validation-time",
        "execution and separate discovery timestamps are not ordered",
    )
    stdout, stderr = (raw[f"{ident}.{suffix}"] for suffix in ("stdout", "stderr"))
    matched = re.search(rb"(?:^|\n)Ran ([0-9]+) tests? in [0-9]+(?:\.[0-9]+)?s\n\nOK\n?\Z", stderr)
    _require(
        matched is not None
        and int(matched.group(1)) == len(names)
        and len(re.findall(rb"(?m)^Ran ", stderr)) == 1
        and re.search(
            rb"(?i)\b(?:skipped|skip|expected.failure|unexpected.success|FAILED|ERROR|FAIL)\b", stdout + b"\n" + stderr
        )
        is None
        and execution.get("stdoutSha256") == hashlib.sha256(stdout).hexdigest()
        and execution.get("stderrSha256") == hashlib.sha256(stderr).hexdigest()
        and result.get(ident) == f"PASS_{len(names)}_TESTS"
        and result.get(f"{ident}StderrSha256") == hashlib.sha256(stderr).hexdigest(),
        "r11-validation-output",
        "suite output is not one complete clean matching result",
    )
    mapping = cases.get("localCaseMapping")
    _require(
        isinstance(mapping, dict)
        and all(
            isinstance(group, list)
            and group
            and all(isinstance(item, str) for item in group)
            and len(set(group)) == len(group)
            and set(group) <= set(names)
            for group in mapping.values()
        ),
        "r11-validation-cases",
        "local case mapping is not bound to discovered cases",
    )
    mapping = _validated_cast(dict[str, Any], mapping)
    block: dict[str, Any] = {
        "schemaVersion": "alk-bootstrap-test-support-shared-roster.v1",
        "commandId": command_id,
        "caseRoster": names,
        "caseRosterSha256": canonical_digest(names),
        "executionReceipt": {k: v for k, v in execution.items() if k != "testNames"},
        "loaderDiscoveryReceipt": {k: v for k, v in discovery.items() if k != "discoveredCaseIds"},
        "stdoutRawBase64": base64.b64encode(stdout).decode("ascii"),
        "stderrRawBase64": base64.b64encode(stderr).decode("ascii"),
    }
    block["executionReceipt"]["testNamesRef"] = "caseRoster"
    block["loaderDiscoveryReceipt"]["discoveredCaseIdsRef"] = "caseRoster"
    _r69h_expand_test_support(block, command_id, execution, discovery, stdout, stderr, oracle)
    return {"content": block, "caseMapping": mapping}


def _r11_match_cost_opening(raw: dict[str, bytes], opening_raw: bytes, contract: dict) -> dict[str, Any]:
    """Preserve unknown coordinator opening; raw origin qualification is external.

    This path never settles measured usage or releases a hold. Shard settlement
    is a distinct raw-usage join, not a caller-authored MEASURED flag here.
    """
    opening = _r11_json(opening_raw, limit=131_072)
    admission, cost = (_r11_json(raw[name], limit=131_072) for name in ("admission.json", "cost.json"))
    held = opening.get("unknownHoldsIncludingThisWindow")
    exposure = opening.get("ledgerLowerBoundIncludingThisHold")
    cap = admission.get("tokenCap")
    policy = contract["accounting"]
    _require(
        opening.get("costStatus") == "UNAVAILABLE"
        and "actualTokens" in opening
        and opening["actualTokens"] is None
        and type(held) is int
        and held >= 0
        and type(exposure) is int
        and exposure >= held
        and type(cap) is int
        and 0 < cap <= policy["totalModelTokensCap"]
        and admission.get("status") == "ADMITTED_PREAPPROVED_BY_USER"
        and isinstance(admission.get("bootstrapAdmissionId"), str)
        and bool(admission["bootstrapAdmissionId"])
        and admission.get("implementationOriginAdmissionId") == "r166-pre-ws01-route-bootstrap"
        and type(admission.get("protectedCloseoutTokens")) is int
        and admission["protectedCloseoutTokens"] >= policy["protectedCloseoutTokens"]
        and admission["protectedCloseoutTokens"] < cap
        and type(admission.get("workAllocation")) is int
        and 0 < admission["workAllocation"] <= policy["workModelTokensCap"]
        and admission["workAllocation"] + admission["protectedCloseoutTokens"] == cap
        and admission.get("costOpeningSha256") == hashlib.sha256(opening_raw).hexdigest()
        and admission.get("priorUnknownHolds") == cost.get("priorUnknownHolds") == held
        and admission.get("priorAccountedExposureLowerBound")
        == cost.get("priorAccountedExposureLowerBound")
        == exposure
        and admission.get("admittedUnknownHolds") == cost.get("heldUnknownTokens") == held + cap
        and admission.get("admittedExposureLowerBound") == cost.get("accountedExposureLowerBound") == exposure + cap
        and cost.get("windowCap") == cap
        and cost.get("admissionSha256") == hashlib.sha256(raw["admission.json"]).hexdigest()
        and cost.get("bootstrapAdmissionId") == admission["bootstrapAdmissionId"]
        and cost.get("implementationOriginAdmissionId") == admission["implementationOriginAdmissionId"]
        and all(
            item.get("costStatus") == "UNAVAILABLE"
            and "actualModelTokens" in item
            and item["actualModelTokens"] is None
            for item in (admission, cost)
        ),
        "r11-support-cost",
        "opening continuity, full hold, reserve or admission differs",
    )
    cap = _validated_cast(int, cap)
    exposure = _validated_cast(int, exposure)
    held = _validated_cast(int, held)
    for key, ceiling in (
        ("maxToolRequests", policy["maxToolRequests"]),
        ("maxTargetedValidationCommands", policy["maxTargetedValidationCommands"]),
        ("maxElapsedSeconds", policy["maxElapsedSeconds"]),
        ("maxModelReviewStarts", 1),
    ):
        _require(
            type(admission.get(key)) is int and 0 <= admission[key] <= ceiling,
            "r11-support-cost",
            "bounded admission exceeds reviewed policy",
        )
    _require(
        type(admission.get("maxNativeLaunches")) is int
        and admission["maxNativeLaunches"] == 0
        and admission.get("paidResponsesApi") is False
        and admission.get("externalMessages") is False,
        "r11-support-cost",
        "bootstrap admission permits an out-of-scope action",
    )
    return {
        "opening": opening,
        "admission": admission,
        "cost": cost,
        "costOpeningSha256": hashlib.sha256(opening_raw).hexdigest(),
    }


def collect_source_review_support(
    project_root: Path, *, support_directory: Path, opening_raw: bytes, role_delivery: bool = False
) -> dict[str, Any]:
    """Reopen the exact 14-key support and recompute its source/test/cost joins.

    Produces CONTENT for the composite subject, never composite PASS or native
    eligibility. Parent, opening origin, transport producer, shard settlement and
    terminal joins are separate; a clean suite summary is not per-case outcome.
    """
    root = Path(project_root).absolute()
    directory = Path(support_directory).absolute()
    oracle, expected, contract, authority = _r11_support_authority(root, role_delivery=role_delivery)
    raw = _r11_private_support(root, directory, oracle["requiredPrivateSupportKeys"])
    sources = capture_review_validation_sources(root)
    current = _r11_wip(root, expected)
    lock_sha = authority["tasks/release-2-16/plan.lock.json"]
    inventories = {name: _r11_json(raw[name + "-wip-inventory.json"], limit=131_072) for name in ("before", "after")}
    for inventory in inventories.values():
        _require(
            set(inventory) == set(oracle["wipBlockRequiredFields"])
            and inventory.get("schemaVersion") == "alk-r11-validation-wip.v1"
            and inventory.get("gitHead") == current["gitHead"]
            and inventory.get("installedLockSha256") == lock_sha
            and type(inventory.get("productPathCount")) is int
            and inventory["productPathCount"] == len(expected["allProductPaths"])
            and isinstance(inventory.get("rows"), list),
            "r11-support-wip",
            "WIP inventory shape or authority differs",
        )
        rows = inventory["rows"]
        _require(
            all(
                isinstance(row, dict)
                and set(row) == set(oracle["wipRowRequiredFields"])
                and isinstance(row.get("path"), str)
                for row in rows
            )
            and [row["path"] for row in rows] == sorted(expected["allProductPaths"]),
            "r11-support-wip",
            "WIP rows are missing, extra, duplicate or unordered",
        )
    # These are final validation snapshots, not the implementation's old baseline.
    # Source changes invalidate tests even when made in a temporarily owned file.
    actual = {
        "schemaVersion": "alk-r11-validation-wip.v1",
        **current,
        "installedLockSha256": lock_sha,
        "productPathCount": len(current["rows"]),
    }
    _require(
        all(canonical_bytes(value) == canonical_bytes(actual) for value in inventories.values()),
        "r11-support-wip",
        "validation WIP differs from current source",
    )
    cost = _r11_match_cost_opening(raw, opening_raw, contract)
    observed = _r11_observe_test_rosters(root, oracle)
    tests = {
        key: _r11_match_test_support(root, key, raw, oracle, contract, sources, observed) for key in ("C34", "C35")
    }
    _require(
        set().union(*(set(value["caseMapping"]) for value in tests.values()))
        == {case["id"] for case in contract["validation"]["cases"]},
        "r11-validation-cases",
        "required validation case mapping is incomplete",
    )
    _require(
        capture_review_validation_sources(root) == sources
        and _r11_wip(root, expected) == current
        and _r11_private_support(root, directory, oracle["requiredPrivateSupportKeys"]) == raw
        and _r11_support_authority(root, role_delivery=role_delivery)[3] == authority,
        "r11-support-stale",
        "source, WIP, support or authority changed during collection",
    )
    content = {
        "wip": inventories,
        "tests": {key: value["content"] for key, value in tests.items()},
        "caseMappings": {key: value["caseMapping"] for key, value in tests.items()},
        **cost,
    }
    return {
        "schemaVersion": "alk-r11-support-match.v1",
        "status": "SUPPORT_MATCHED",
        "content": content,
        "supportEvidenceSha256": canonical_digest(content),
        "validationEvidenceSha256": canonical_digest(
            {key: value for key, value in content.items() if key in {"wip", "tests", "caseMappings"}}
        ),
        "privateSupportReceiptDigests": {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
        "validationSourcesSha256": canonical_digest(sources),
        "authoritySha256": authority,
        "costOpeningSha256": cost["costOpeningSha256"],
        "costStatus": "UNAVAILABLE",
        "heldUnknownTokens": cost["cost"]["heldUnknownTokens"],
        "openingProvenanceQualified": False,
        "producerQualified": False,
        "firstNativeBootstrapEligible": False,
    }


class _R11AppServerPipe:
    """Worker-owned blocking pipe; the enclosing process enforces the deadline.

    Every received chunk is durable before parsing, including partial/invalid
    frames. The separate review transcript records the exact review RPC lane.
    This class must never run in a coordinator callback/thread.
    """

    def __init__(self, root: Path, binding: dict[str, str], reader: Any, writer: Any) -> None:
        raise LifecycleError(
            "r11-experimental-disabled", "Experimental R11 review route is disabled; use ordinary independent audit"
        )
        from .private_input import _private_dir

        self.root, self.reader, self.writer = root, reader, writer
        self.directory = root / _R11_REVIEW_ROOT / "shards" / binding["shardId"] / "host-wire"
        _private_dir(self.directory.parent, boundary=root)
        self.directory.mkdir(mode=0o700)  # Exclusive even after a partial launch.
        self.sequence = 0
        self.total = 0
        self.buffer = bytearray()
        self.failed = False
        self.record("SESSION", canonical_bytes(binding))

    def record(self, kind: str, raw: bytes) -> None:
        raise LifecycleError(
            "r11-experimental-disabled", "Experimental R11 review route is disabled; use ordinary independent audit"
        )
        _require(
            not self.failed and isinstance(raw, bytes) and self.total + len(raw) <= 8_388_608,
            "r11-host-wire-limit",
            "host wire is failed or exceeds its byte cap",
        )
        raw = _validated_cast(bytes, raw)
        try:
            for offset in range(0, max(1, len(raw)), 32_768):
                _require(self.sequence < 65_536, "r11-host-wire-limit", "host wire record cap exceeded")
                _write(
                    self.root,
                    self.directory / f"{self.sequence:08d}.json",
                    {
                        "sequence": self.sequence,
                        "monotonicNs": time.monotonic_ns(),
                        "kind": kind,
                        "offset": offset,
                        "bytes": len(raw),
                        "rawHex": raw[offset : offset + 32_768].hex(),
                    },
                )
                self.sequence += 1
            _sync_directory(self.directory)
            self.total += len(raw)
        except BaseException:
            self.failed = True
            raise

    def send_bootstrap(self, value: dict[str, Any]) -> None:
        raise LifecycleError(
            "r11-experimental-disabled", "Experimental R11 review route is disabled; use ordinary independent audit"
        )
        _require(
            value.get("method")
            in {"initialize", "initialized", "model/list", "thread/resume", "thread/start", "thread/read"},
            "r11-host-bootstrap",
            "bootstrap lane cannot send a model/tool request",
        )
        raw = canonical_bytes(value) + b"\n"
        self.record("SEND_PENDING", raw)
        try:
            offset = 0
            while offset < len(raw):
                count = self.writer.write(raw[offset:])
                _require(
                    type(count) is int and 0 < count <= len(raw) - offset,
                    "r11-host-write",
                    "bootstrap write made no valid progress",
                )
                count = _validated_cast(int, count)
                self.record("WRITE_ACCEPTED", raw[offset : offset + count])
                offset += count
            self.writer.flush()
            self.record("FLUSHED", canonical_bytes({"sha256": hashlib.sha256(raw).hexdigest()}))
        except BaseException:
            self.failed = True
            raise

    def receive(self, transcript: _TranscriptReceiver | None = None) -> tuple[bytes, dict[str, Any]]:
        raise LifecycleError(
            "r11-experimental-disabled", "Experimental R11 review route is disabled; use ordinary independent audit"
        )
        try:
            while b"\n" not in self.buffer:
                chunk = os.read(self.reader.fileno(), 65_536)
                self.record("RECEIVED_CHUNK", chunk)
                _require(bool(chunk), "r11-host-eof", "host closed before a complete RPC frame")
                self.buffer.extend(chunk)
                _require(
                    len(self.buffer.split(b"\n", 1)[0]) < 2_097_152,
                    "r11-host-frame-limit",
                    "host RPC frame exceeds its bound",
                )
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer[:] = rest
            raw = bytes(line) + b"\n"
            _require(len(raw) <= 2_097_152, "r11-host-frame-limit", "host RPC frame exceeds its bound")
            if transcript is not None:
                transcript.receive(raw)
            value = _r11_json(raw, limit=2_097_152)
            _require("jsonrpc" not in value or value["jsonrpc"] == "2.0", "r11-host-rpc", "unexpected RPC framing")
            return raw, value
        except BaseException:
            self.failed = True
            raise

    def bootstrap_reply(self, ident: int, thread_id: str | None) -> dict[str, Any]:
        raise LifecycleError(
            "r11-experimental-disabled", "Experimental R11 review route is disabled; use ordinary independent audit"
        )
        for _ in range(256):
            _, value = self.receive()
            if "id" in value:
                _require(
                    type(value["id"]) is int
                    and value["id"] == ident
                    and set(value) <= {"id", "result", "jsonrpc"}
                    and isinstance(value.get("result"), dict),
                    "r11-host-rpc",
                    "bootstrap RPC failed or returned an unexpected request/response",
                )
                return value["result"]
            method, params = value.get("method"), _validated_cast(dict[str, Any], value.get("params"))
            _require(
                _r11_notification_envelope(value)
                and (
                    method
                    in {
                        "account/updated",
                        "account/rateLimits/updated",
                        "deprecationNotice",
                        "mcpServer/startupStatus/updated",
                        "remoteControl/status/changed",
                    }
                    or (
                        method == "thread/started"
                        and isinstance(params.get("thread"), dict)
                        and isinstance(params["thread"].get("id"), str)
                        and (thread_id is None or params["thread"]["id"] == thread_id)
                    )
                    or (method == "thread/status/changed" and params.get("threadId") == thread_id)
                ),
                "r11-host-rpc",
                "unexpected bootstrap notification; no model/tool action authorized",
            )
        raise LifecycleError("r11-host-rpc", "bootstrap notification bound exceeded")


def _r11_host_snapshot(root: Path, binding: dict[str, str]) -> dict[str, bytes]:
    base = root / _R11_REVIEW_ROOT / "shards" / binding["shardId"]
    result: dict[str, bytes] = {}
    total = 0
    for lane in ("host-process", "host-wire"):
        directory = base / lane
        try:
            mode = directory.lstat().st_mode
        except OSError as exc:
            raise LifecycleError("r11-host-inventory", "host evidence directory unavailable") from exc
        _require(
            stat.S_ISDIR(mode) and mode & 0o077 == 0,
            "r11-host-inventory",
            "host evidence directory is indirect or nonprivate",
        )
        names = {path.name for path in directory.iterdir()}
        if lane == "host-process":
            expected = {"launch.json", "finished.json"}
        else:
            count = len(names) - 1
            _require(1 <= count <= 65_536, "r11-host-inventory", "host wire record count is invalid")
            expected = {f"{i:08d}.json" for i in range(count)} | {"exchange.json"}
        _require(names == expected, "r11-host-inventory", "host evidence is incomplete, pending or extra")
        for name in sorted(names):
            raw = _r11_review_private(root, directory / name)
            total += len(raw)
            _require(total <= 33_554_432, "r11-host-inventory", "host evidence exceeds bounded inventory")
            result[lane + "/" + name] = raw
    return result


def _r11_host_records(snapshot: dict[str, bytes], start_ns: int, finish_ns: int) -> list[dict[str, Any]]:
    groups = []
    active = None
    last_ns = start_ns
    total = 0
    names = sorted(name for name in snapshot if name.startswith("host-wire/") and not name.endswith("/exchange.json"))
    for index, name in enumerate(names):
        row = _r11_json(snapshot[name], limit=131_072)
        _require(
            snapshot[name] == canonical_bytes(row)
            and set(row) == {"sequence", "monotonicNs", "kind", "offset", "bytes", "rawHex"}
            and type(row["sequence"]) is int
            and row["sequence"] == index
            and type(row["monotonicNs"]) is int
            and last_ns <= row["monotonicNs"] <= finish_ns
            and row["kind"] in {"SESSION", "SEND_PENDING", "WRITE_ACCEPTED", "FLUSHED", "RECEIVED_CHUNK"}
            and type(row["offset"]) is int
            and row["offset"] >= 0
            and type(row["bytes"]) is int
            and 0 <= row["bytes"] <= 8_388_608
            and isinstance(row["rawHex"], str)
            and re.fullmatch("[0-9a-f]*", row["rawHex"]) is not None
            and len(row["rawHex"]) <= 65_536
            and len(row["rawHex"]) % 2 == 0,
            "r11-host-record",
            "invalid host record, order, framing or process time",
        )
        last_ns = row["monotonicNs"]
        if active is None:
            _require(row["offset"] == 0, "r11-host-record", "host record parts start with a gap")
            active = {
                "kind": row["kind"],
                "size": row["bytes"],
                "raw": bytearray(),
                "firstNs": last_ns,
                "lastNs": last_ns,
            }
        _require(
            row["kind"] == active["kind"] and row["bytes"] == active["size"] and row["offset"] == len(active["raw"]),
            "r11-host-record",
            "host parts differ in kind, size or contiguous offset",
        )
        part = bytes.fromhex(row["rawHex"])
        _require(
            len(part) == min(32_768, active["size"] - len(active["raw"])), "r11-host-record", "host part size differs"
        )
        active["raw"].extend(part)
        active["lastNs"] = last_ns
        total += len(part)
        _require(total <= 8_388_608, "r11-host-record", "raw host byte cap exceeded")
        if len(active["raw"]) == active["size"]:
            active["raw"] = bytes(active["raw"])
            groups.append(active)
            active = None
    _require(active is None, "r11-host-record", "host record ends in a partial group")
    return groups


def _r11_replay_prelude_groups(
    groups: list[dict], binding: dict, planned_binding: dict | None, role_delivery: bool, expected: list[dict]
) -> tuple[bytearray, dict | None, object, list[dict], int | None, list[dict]]:
    sent = 0
    pending: dict[str, Any] | None = None
    waiting: object = None
    replies = []
    buffered = bytearray()
    review_chunks = []
    bootstrap_finished_ns = None
    for group in groups[1:]:
        kind, raw = group["kind"], group["raw"]
        if bootstrap_finished_ns is not None:
            _require(
                kind == "RECEIVED_CHUNK" and bool(raw), "r11-host-prelude", "unexpected send or EOF after bootstrap"
            )
            review_chunks.append(group)
            continue
        if kind == "SEND_PENDING":
            _require(
                sent < len(expected)
                and pending is None
                and waiting is None
                and (not buffered or planned_binding is not None or role_delivery)
                and raw == canonical_bytes(expected[sent]) + b"\n",
                "r11-host-prelude",
                "bootstrap request was skipped, repeated, changed or concurrent",
            )
            pending = {"raw": raw, "accepted": 0}
        elif kind == "WRITE_ACCEPTED":
            _require(
                pending is not None
                and raw
                and pending["raw"][pending["accepted"] : pending["accepted"] + len(raw)] == raw,
                "r11-host-prelude",
                "bootstrap write differs from pending bytes",
            )
            _validated_cast(dict[str, Any], pending)["accepted"] += len(raw)
        elif kind == "FLUSHED":
            _require(
                pending is not None
                and pending["accepted"] == len(pending["raw"])
                and raw == canonical_bytes({"sha256": hashlib.sha256(pending["raw"]).hexdigest()}),
                "r11-host-prelude",
                "bootstrap write or flush is incomplete",
            )
            waiting = expected[sent].get("id")
            sent += 1
            pending = None
        elif kind == "RECEIVED_CHUNK":
            _require(
                (waiting is not None or planned_binding is not None or role_delivery) and pending is None and raw,
                "r11-host-prelude",
                "host response precedes a flushed request",
            )
            buffered.extend(raw)
            while b"\n" in buffered:
                line, _, rest = buffered.partition(b"\n")
                buffered[:] = rest
                message = _r11_json(bytes(line) + b"\n", limit=2_097_152)
                _require(
                    "jsonrpc" not in message or message["jsonrpc"] == "2.0",
                    "r11-host-prelude",
                    "host RPC framing differs",
                )
                if "id" in message:
                    _require(
                        type(message["id"]) is int
                        and message["id"] == waiting
                        and set(message) <= {"id", "result", "jsonrpc"}
                        and isinstance(message.get("result"), dict),
                        "r11-host-prelude",
                        "host error, tool request or foreign response",
                    )
                    replies.append(message["result"])
                    waiting = None
                    _require(
                        not buffered or planned_binding is not None,
                        "r11-host-prelude",
                        "coalesced unconsumed bootstrap bytes",
                    )
                    if sent == len(expected):
                        bootstrap_finished_ns = group["lastNs"]
                else:
                    params = _validated_cast(dict[str, Any], message.get("params"))
                    _require(
                        _r11_notification_envelope(message)
                        and (
                            message.get("method")
                            in {
                                "account/updated",
                                "account/rateLimits/updated",
                                "deprecationNotice",
                                "mcpServer/startupStatus/updated",
                                "remoteControl/status/changed",
                            }
                            or (
                                message.get("method") == "thread/started"
                                and isinstance(params.get("thread"), dict)
                                and params["thread"].get("id") == binding["threadId"]
                            )
                            or (
                                message.get("method") == "thread/status/changed"
                                and params.get("threadId") == binding["threadId"]
                            )
                        ),
                        "r11-host-prelude",
                        "bootstrap notification differs",
                    )
            _require(len(buffered) < 2_097_152, "r11-host-prelude", "bootstrap frame exceeds its bound")
        else:
            raise LifecycleError("r11-host-prelude", "unexpected repeated host session")
    return buffered, pending, waiting, replies, bootstrap_finished_ns, review_chunks


def _r11_match_host_prelude(
    root: Path,
    binding: dict[str, str],
    model: str,
    groups: list[dict[str, Any]],
    *,
    planned_binding: dict[str, str] | None = None,
    role_delivery: bool = False,
) -> dict[str, Any]:
    _require(
        role_delivery is True and planned_binding is None,
        "r11-v5-runtime-retired",
        "current review execution requires explicit v6 role delivery",
    )
    _require(
        type(role_delivery) is bool and (not role_delivery or planned_binding is None),
        "r11-host-mode",
        "v6 metadata origin cannot mix with a v5 planned dispatch",
    )
    expected: list[dict[str, Any]] = [
        {
            "id": 1_000_001,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "agent_lifecycle_kit", "title": "Agent Lifecycle Kit", "version": "2.16.0"}
            },
        },
        {"method": "initialized", "params": {}},
        {"id": 1_000_002, "method": "model/list", "params": {"limit": 100, "includeHidden": True}},
        {
            "id": 1_000_003,
            "method": "thread/resume",
            "params": {"threadId": binding["threadId"], "model": model, "cwd": str(root), "approvalPolicy": "never"},
        },
    ]
    expected.append(
        {"id": 1_000_004, "method": "thread/read", "params": {"threadId": binding["threadId"], "includeTurns": False}}
    )
    _require(
        bool(groups)
        and groups[0]["kind"] == "SESSION"
        and groups[0]["raw"] == canonical_bytes(planned_binding or binding),
        "r11-host-prelude",
        "host session identity differs",
    )
    buffered, pending, waiting, replies, bootstrap_finished_ns, review_chunks = _r11_replay_prelude_groups(
        groups, binding, planned_binding, role_delivery, expected
    )
    _require(
        not buffered
        and pending is None
        and waiting is None
        and len(replies) == len(expected) - 1
        and bootstrap_finished_ns is not None
        and bool(review_chunks),
        "r11-host-prelude",
        "bootstrap or review receive lane is incomplete",
    )
    initialization, catalog, resume = replies[:3]
    _require(
        isinstance(catalog.get("data"), list)
        and len([row for row in catalog["data"] if isinstance(row, dict) and row.get("model") == model]) == 1
        and resume.get("model") == model
        and isinstance(resume.get("thread"), dict)
        and resume["thread"].get("id") == binding["threadId"]
        and resume["thread"].get("turns") == [],
        "r11-host-prelude",
        "catalog/model/thread-empty evidence differs",
    )
    _require(
        _r11_fresh_start(resume, model) == binding["threadId"]
        and _r11_fresh_start({**replies[3], "model": model}, model) == binding["threadId"],
        "r11-host-prelude",
        "created thread differs from sealed dispatch",
    )
    return {
        "initializeSha256": canonical_digest(initialization),
        "catalogSha256": canonical_digest(catalog),
        ("resumeSha256"): canonical_digest(resume),
        **({"summarySha256": canonical_digest(replies[3])}),
        "bootstrapFinishedNs": bootstrap_finished_ns,
        "reviewChunks": review_chunks,
    }


def _r11_empty_thread_exchange(wire: Any, root: Path, model: str, count: int) -> dict[str, Any]:
    """Reconstruct a fixed metadata sequence from already saved raw records."""
    _require(
        type(wire) is _R11PreparationReplay
        and set(vars(wire)) == {"groups", "cursor", "buffer"}
        and type(wire.groups) is list
        and type(wire.cursor) is int
        and type(wire.buffer) is bytearray
        and all(
            type(row) is dict and type(row.get("kind")) is str and type(row.get("raw")) is bytes for row in wire.groups
        ),
        "r11-experimental-disabled",
        "Only side-effect-free saved preparation replay is supported",
    )
    _require(type(count) is int and 1 <= count <= 4, "r11-thread-count", "one to four fresh threads required")
    count = _validated_cast(int, count)
    wire.send_bootstrap(
        {
            "id": 1_000_001,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "agent_lifecycle_kit", "title": "Agent Lifecycle Kit", "version": "2.16.0"},
                "capabilities": {"experimentalApi": True},
            },
        }
    )
    initialization = wire.bootstrap_reply(1_000_001, "")
    wire.send_bootstrap({"method": "initialized", "params": {}})
    ids, evidence = [], []
    for index in range(count):
        ident = 1_000_100 + index * 3
        wire.send_bootstrap(
            {
                "id": ident,
                "method": "thread/start",
                "params": {
                    "model": model,
                    "cwd": str(root),
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "historyMode": "legacy",
                },
            }
        )
        started = wire.bootstrap_reply(ident, None)
        thread = started.get("thread")
        _require(
            isinstance(thread, dict)
            and _r11_role_schema_matches(thread.get("id"), {"type": "string", "minLength": 1, "maxLength": 256})
            and thread["id"] not in ids
            and thread.get("ephemeral") is False
            and thread.get("forkedFromId") is None
            and thread.get("historyMode") == "legacy"
            and started.get("model") == model,
            "r11-thread-start",
            "fresh distinct persistent thread and selected model not confirmed",
        )
        thread = _validated_cast(dict[str, Any], thread)
        thread_id = thread["id"]
        reads = []
        for offset in (1, 2):
            wire.send_bootstrap(
                {"id": ident + offset, "method": "thread/read", "params": {"threadId": thread_id, "includeTurns": True}}
            )
            result = wire.bootstrap_reply(ident + offset, thread_id)
            observed = result.get("thread")
            _require(
                isinstance(observed, dict)
                and observed.get("id") == thread_id
                and observed.get("turns") == []
                and observed.get("ephemeral") is False
                and observed.get("forkedFromId") is None
                and observed.get("historyMode") == "legacy"
                and observed.get("status", {}).get("type") in {"idle", "notLoaded"},
                "r11-thread-history",
                "complete empty inactive thread history is not confirmed",
            )
            observed = _validated_cast(dict[str, Any], observed)
            reads.append(result)
        _require(reads[0] == reads[1], "r11-thread-history", "fresh thread changed between ordered reads")
        ids.append(thread_id)
        evidence.append({"startSha256": canonical_digest(started), "emptyReadSha256": canonical_digest(reads[0])})
    _require(not wire.buffer, "r11-thread-pending", "unconsumed bytes after empty-thread reads")
    return {
        "schemaVersion": "alk-r11-empty-threads.v1",
        "status": "EMPTY_THREADS_OBSERVED",
        "model": model,
        "threadIds": ids,
        "threadEvidence": evidence,
        "initializeSha256": canonical_digest(initialization),
        "modelRequestsSent": 0,
        "producerQualified": False,
        "firstNativeBootstrapEligible": False,
        "retryAuthorized": False,
    }


class _R11PreparationReplay(_R11AppServerPipe):
    """Reconstruct exact accepted writes/flushes and received bytes; never execute IO."""

    buffer: bytearray

    def __init__(self, groups: list[dict[str, Any]], binding: dict[str, str]) -> None:
        self.groups, self.cursor, self.buffer = groups, 1, bytearray()
        _require(
            bool(groups) and groups[0]["kind"] == "SESSION" and groups[0]["raw"] == canonical_bytes(binding),
            "r11-thread-wire",
            "preparation session differs",
        )

    def bootstrap_reply(self, ident: int, thread_id: str | None) -> dict[str, Any]:
        for _ in range(256):
            _, value = self.receive()
            if "id" in value:
                _require(
                    type(value["id"]) is int
                    and value["id"] == ident
                    and set(value) <= {"id", "result", "jsonrpc"}
                    and isinstance(value.get("result"), dict),
                    "r11-host-rpc",
                    "bootstrap RPC failed or returned an unexpected request/response",
                )
                return value["result"]
            method, params = value.get("method"), _validated_cast(dict[str, Any], value.get("params"))
            _require(
                _r11_notification_envelope(value)
                and (
                    method
                    in {
                        "account/updated",
                        "account/rateLimits/updated",
                        "deprecationNotice",
                        "mcpServer/startupStatus/updated",
                        "remoteControl/status/changed",
                    }
                    or (
                        method == "thread/started"
                        and isinstance(params.get("thread"), dict)
                        and isinstance(params["thread"].get("id"), str)
                        and (thread_id is None or params["thread"]["id"] == thread_id)
                    )
                    or (method == "thread/status/changed" and params.get("threadId") == thread_id)
                ),
                "r11-host-rpc",
                "unexpected bootstrap notification; no model/tool action authorized",
            )
        raise LifecycleError("r11-host-rpc", "bootstrap notification bound exceeded")

    def take(self, kind: str) -> bytes:
        _require(
            self.cursor < len(self.groups) and self.groups[self.cursor]["kind"] == kind,
            "r11-thread-wire",
            "missing, reordered or extra preparation IO",
        )
        raw = self.groups[self.cursor]["raw"]
        self.cursor += 1
        return raw

    def send_bootstrap(self, value: dict[str, Any]) -> None:
        raw = canonical_bytes(value) + b"\n"
        _require(self.take("SEND_PENDING") == raw, "r11-thread-wire", "actual metadata request differs")
        accepted = bytearray()
        while len(accepted) < len(raw):
            part = self.take("WRITE_ACCEPTED")
            _require(bool(part), "r11-thread-wire", "preparation write made no progress")
            accepted.extend(part)
        _require(
            bytes(accepted) == raw
            and self.take("FLUSHED") == canonical_bytes({"sha256": hashlib.sha256(raw).hexdigest()}),
            "r11-thread-wire",
            "accepted metadata request bytes/flush differ",
        )

    def receive(self, transcript: Any = None) -> tuple[bytes, dict[str, Any]]:
        _compatibility_arguments = (transcript,)
        while b"\n" not in self.buffer:
            chunk = self.take("RECEIVED_CHUNK")
            _require(bool(chunk), "r11-thread-wire", "preparation EOF before response")
            self.buffer.extend(chunk)
            _require(
                len(self.buffer.split(b"\n", 1)[0]) < 2_097_152, "r11-thread-wire", "preparation response too large"
            )
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer[:] = rest
        raw = bytes(line) + b"\n"
        value = _r11_json(raw, limit=2_097_152)
        _require("jsonrpc" not in value or value["jsonrpc"] == "2.0", "r11-thread-wire", "invalid RPC version")
        return raw, value
