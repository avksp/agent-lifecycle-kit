"""Read-only recomputation of one independently anchored native run."""

from __future__ import annotations

import errno
import hashlib
import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from itertools import islice
from pathlib import Path
from typing import Any

from agent_lifecycle.audit.proof_chain import validate_receipt_hash_chain
from agent_lifecycle.contracts.authority_io import hold_authority_directory, open_authority_read
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.chain_verification_schemas import ANCHOR, BUNDLE, REPORT, TRUST, validate_chain_input
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.implementation_audit_validation import (
    require_implementation_audit_accepted,
    validate_final_audit_outcome_report,
    validate_final_implementation_audit,
    validate_implementation_audit_report,
)
from agent_lifecycle.contracts.operator_signature import (
    FREEZE_SIGNATURE_NAME,
    expected_operator_decision,
    verify_operator_envelope,
)
from agent_lifecycle.contracts.operator_signature_schemas import (
    operator_interval,
    require_operator_authority,
    validate_operator_envelope,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.review_verdict import open_blocking_finding_ids
from agent_lifecycle.contracts.reviewer_identity_schemas import (
    REVIEWER_REQUIRED_LOCK,
    REVIEWER_REQUIRED_STATE,
    parse_reviewer_utc,
)
from agent_lifecycle.contracts.workflow_authorization_schemas import validate_workflow_authorization_receipt
from agent_lifecycle.contracts.workflow_state_authority import decode_workflow_authority
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from agent_lifecycle.contracts.workflow_storage_schemas import SNAPSHOT_KIND, is_initial_snapshot_lineage
from agent_lifecycle.freeze.package_integrity import verify_archived_reviewer_package, verify_plan_lock_envelope
from agent_lifecycle.specification.completion_signal import validate_completion_signal
from agent_lifecycle.workflow.final_proof_integrity import validate_final_proof_integrity
from agent_lifecycle.workflow.reviewer_gate import final_reviewer_decision_from_manifest, task_reviewer_decision
from agent_lifecycle.workflow.reviews import validate_archived_task_result, validate_archived_task_review

_MAX_FILES = 1024
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 64 * 1024 * 1024
_WINDOWS_CANT_RESOLVE_FILENAME = 1921
_START_EVENTS = ("plan-adopted", "execution-authorized", "execution-started")
_FINISH_EVENTS = ("final-audit-outcome-applied", "run-finalized")
_TASK_EVENTS = ("task-started", "task-result-committed", "task-accepted")
_SUPPORTED_EVENTS = set(_START_EVENTS + _FINISH_EVENTS + _TASK_EVENTS)
_LINEAGE = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")


class _Incomplete(LifecycleError):
    """A well-formed selection does not provide a supported proof."""


def _ensure(condition: bool, code: str) -> None:
    if not condition:
        raise LifecycleError(code, "Chain verification mismatch")


def _object(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "Expected a bound object")
    return value


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bounded_file(root: Path, path: Path, cap: int) -> bytes:
    with open_authority_read(path, root=root, runtime_aliases=False) as handle:
        info = os.fstat(handle.fileno())
        _ensure(info.st_nlink == 1, "chain-input-hardlink")
        _ensure(info.st_size <= cap, "chain-input-byte-limit")
        value = handle.read(cap + 1)
    _ensure(len(value) <= cap, "chain-input-byte-limit")
    return value


class _Snapshot:
    """Read exact bytes once per canonical evidence selector."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, bytes] = {}
        self.directories: dict[str, list[tuple[str, bool, bool]]] = {}
        self.spellings: dict[str, str] = {}
        self.total = 0

    def read(self, path: str) -> bytes:
        _ensure(isinstance(path, str) and normalize_repo_path(path) == path, "chain-input-path")
        if path in self.files:
            return self.files[path]
        _ensure(len(self.files) < _MAX_FILES, "chain-input-file-limit")
        _ensure(path.casefold() not in self.spellings, "chain-input-alias")
        raw = _bounded_file(self.root, self.root / path, min(_MAX_FILE_BYTES, _MAX_TOTAL_BYTES - self.total))
        self.files[path] = raw
        self.spellings[path.casefold()] = path
        self.total += len(raw)
        return raw

    def members(self, path: str) -> list[tuple[str, bool, bool]]:
        if path not in self.directories:
            self.directories[path] = self._members(path)
        return self.directories[path]

    def _members(self, path: str) -> list[tuple[str, bool, bool]]:
        directory = self.root / path
        with (
            hold_authority_directory(directory, root=self.root, runtime_aliases=False) as held,
            os.scandir(held.fd if held.fd is not None else directory) as children,
        ):
            entries = []
            for item in islice(children, _MAX_FILES + 1):
                entries.append((item.name, item.is_symlink(), item.is_dir(follow_symlinks=False)))
            _ensure(len(entries) <= _MAX_FILES, "chain-lock-directory-limit")
            return sorted(entries)

    def require_stable(self) -> None:
        for path, raw in self.files.items():
            _ensure(_bounded_file(self.root, self.root / path, len(raw)) == raw, "chain-input-changed")
        for path, members in self.directories.items():
            _ensure(self._members(path) == members, "chain-input-directory-changed")

    def object(self, path: str) -> dict[str, Any]:
        return load_json_object(self.read(path), label="chain evidence")

    def identity(self, summary: Any) -> tuple[str, dict[str, Any]]:
        selected = _object(summary, "chain-artifact-identity-missing")
        path = selected.get("path")
        if not isinstance(path, str):
            raise LifecycleError("chain-artifact-path-missing", "Expected a receipt path")
        raw = self.read(path)
        data = load_json_object(raw, label="native receipt")
        _ensure(
            raw == canonical_bytes(data) + b"\n" and len(raw) == selected.get("bytes"), "chain-artifact-bytes-mismatch"
        )
        _ensure(canonical_digest(data) == selected.get("sha256"), "chain-artifact-digest-mismatch")
        return path, data


def verify_chain(
    repository_root: Path, bundle_path: str, *, trust_config_path: Path, anchor_path: Path
) -> dict[str, Any]:
    """Verify a selected snapshot and return one stable exit classification."""
    checks: list[dict[str, str]] = []
    phase = "input"
    try:
        root = repository_root.absolute()
        _require_canonical_selector(root, "chain-evidence-root-not-canonical")
        snapshot = _Snapshot(root)
        bundle = validate_chain_input(snapshot.object(bundle_path), BUNDLE)
        trust_raw = _trusted_input(root, trust_config_path)
        trust = validate_chain_input(load_json_object(trust_raw), TRUST)
        anchor_raw = _trusted_input(root, anchor_path)
        anchor = validate_chain_input(load_json_object(anchor_raw), ANCHOR)
        phase = "anchor"
        _ensure(anchor["bundleSha256"] == _digest(snapshot.read(bundle_path)), "chain-anchor-bundle-mismatch")
        _ensure(anchor["trustConfigSha256"] == _digest(trust_raw), "chain-anchor-trust-mismatch")
        checks.append({"check": phase, "status": "VERIFIED"})

        phase = "lock"
        manifest, lock = _verify_lock(snapshot, bundle, anchor, trust)
        checks.append({"check": phase, "status": "VERIFIED"})

        phase = "state-journal"
        state, events = _verify_native_state(snapshot, bundle, anchor, manifest, lock)
        checks.append({"check": phase, "status": "VERIFIED"})

        phase = "reviewer-signatures"
        _verify_reviewer_receipts(snapshot, manifest, state, events)
        checks.append({"check": phase, "status": "VERIFIED"})

        phase = "operator-signatures"
        applicable = _verify_operator_receipts(snapshot, bundle, manifest, lock, state, events)
        if applicable:
            checks.append({"check": phase, "status": "VERIFIED"})
        else:
            checks.append(
                {
                    "check": phase,
                    "status": "NOT_APPLICABLE",
                    "reason": "operator-signature-profile-disabled",
                }
            )

        phase = "receipt-chain"
        _verify_chain_artifacts(snapshot, bundle, anchor, state, bundle_path)
        checks.append({"check": phase, "status": "VERIFIED"})
        checks.append({"check": "receipt-membership", "status": "VERIFIED"})

        phase = "snapshot"
        snapshot.require_stable()
        _ensure(
            _trusted_input(root, trust_config_path) == trust_raw and _trusted_input(root, anchor_path) == anchor_raw,
            "chain-trusted-input-changed",
        )
        checks.append({"check": phase, "status": "VERIFIED"})
    except _Incomplete as exc:
        return _report("NOT_CHECKED", 1, checks, phase, exc.code)
    except LifecycleError as exc:
        if phase == "input" or exc.code == "authority-input-unavailable":
            return _report("INVALID_INPUT", 2, checks, phase, exc.code)
        return _report("MISMATCH", 1, checks, phase, exc.code)
    except FileNotFoundError:
        return _report(
            "INVALID_INPUT" if phase == "input" else "MISMATCH",
            2 if phase == "input" else 1,
            checks,
            phase,
            "chain-input-missing",
        )
    except OSError:
        return _report("INVALID_INPUT", 2, checks, phase, "chain-input-unreadable")
    except (TypeError, KeyError, ValueError, RecursionError):
        return _report(
            "INVALID_INPUT" if phase == "input" else "MISMATCH",
            2 if phase == "input" else 1,
            checks,
            phase,
            "chain-input-malformed",
        )
    return _report("VERIFIED", 0, checks)


def _require_canonical_selector(path: Path, code: str) -> None:
    try:
        resolved = path.resolve(strict=True)
    except RuntimeError as exc:
        # Path.resolve uses RuntimeError for a symlink loop on Python 3.11 and 3.12.
        raise LifecycleError(code, "Unable to resolve an explicit verification input") from exc
    except OSError as exc:
        if exc.errno != errno.ELOOP and getattr(exc, "winerror", None) != _WINDOWS_CANT_RESOLVE_FILENAME:
            raise
        raise LifecycleError(code, "Unable to resolve an explicit verification input") from exc
    _ensure(resolved == path, code)


def _trusted_input(root: Path, path: Path) -> bytes:
    selected = path.absolute()
    _require_canonical_selector(selected, "chain-trust-path-not-canonical")
    _ensure(not selected.is_relative_to(root), "chain-trust-inside-evidence-root")
    return _bounded_file(selected.parent, selected, _MAX_FILE_BYTES)


def _report(
    status: str, code: int, checks: list[dict[str, str]], phase: str | None = None, reason: str | None = None
) -> dict[str, Any]:
    return {
        "schemaVersion": REPORT,
        "status": status,
        "exitCode": code,
        "checks": checks,
        "firstFailure": None if phase is None else {"check": phase, "code": reason},
        "scope": "Exact selected run and receipts under verifier-supplied public policy and terminal anchor",
        "authorityGranted": False,
    }


def _verify_lock(
    evidence: _Snapshot, bundle: dict[str, Any], anchor: dict[str, Any], trust: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = evidence.object(bundle["manifest"])
    lock = evidence.object(bundle["lock"])
    if lock.get("schemaVersion") != REVIEWER_REQUIRED_LOCK or manifest.get("status") != "FROZEN":
        raise _Incomplete("chain-lock-profile-unsupported", "Expected one reviewed strict frozen plan")
    joined = verify_plan_lock_envelope(manifest, lock)
    root = normalize_repo_path(manifest["package"]["planArtifactRoot"])
    _ensure(bundle["manifest"] == f"{root}/plan.manifest.json", "chain-manifest-selector-mismatch")
    _ensure(bundle["lock"] == f"{root}/plan.lock.json", "chain-lock-selector-mismatch")
    _ensure(joined["manifestHash"] == anchor["planDigest"], "chain-anchor-plan-mismatch")
    _ensure(_digest(evidence.read(bundle["lock"])) == anchor["lockSha256"], "chain-anchor-lock-mismatch")
    _ensure(joined["packageId"] == anchor["packageId"], "chain-anchor-package-mismatch")
    _ensure(manifest.get("baseRevision", {}).get("sha") == anchor["sourceRevision"], "chain-anchor-source-mismatch")
    _ensure(
        canonical_digest(manifest["reviewerAttestationPolicy"]) == trust["reviewerPolicyDigest"],
        "chain-reviewer-trust-mismatch",
    )
    operator = require_operator_authority(manifest)
    _ensure(
        (canonical_digest(operator) if operator else None) == trust["operatorPolicyDigest"],
        "chain-operator-trust-mismatch",
    )
    entries = joined["entries"]
    _ensure([entry["path"] for entry in entries] == manifest["planFiles"], "chain-lock-inventory-mismatch")
    _ensure(bundle["manifest"] in manifest["planFiles"], "chain-manifest-unbound")
    for entry in entries:
        raw = evidence.read(entry["path"])
        _ensure(_digest(raw) == entry["sha256"] and len(raw) == entry["bytes"], "chain-lock-file-mismatch")
    verify_archived_reviewer_package(
        manifest, lock, root, repository_root=evidence.root, read=evidence.read, members=evidence.members(root)
    )
    acceptance = _object(manifest.get("acceptance"), "chain-plan-acceptance-missing")
    evidence_entries = acceptance.get("evidence", [])
    _ensure(isinstance(evidence_entries, list), "chain-plan-evidence-invalid")
    for item in evidence_entries:
        if _object(item, "chain-plan-evidence-invalid").get("validation"):
            raise _Incomplete("chain-structured-evidence-unsupported", "Selected plan requires extra evidence checks")
    return manifest, lock


def _verify_native_state(
    evidence: _Snapshot, bundle: dict[str, Any], anchor: dict[str, Any], manifest: dict[str, Any], lock: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = evidence.read(bundle["state"])
    _ensure(_digest(raw) == anchor["stateSha256"], "chain-anchor-state-mismatch")
    body = load_json_object(raw, label="anchored state")
    if body.get("schemaVersion") != REVIEWER_REQUIRED_STATE or body.get("phase") != "COMPLETE":
        raise _Incomplete("chain-state-profile-unsupported", "Expected one terminal strict native run")
    with StorageOperation(
        evidence.root, state_path=evidence.root / bundle["state"], runtime_aliases=False
    ) as operation:
        state = decode_workflow_authority(
            raw,
            root=evidence.root,
            state_path=evidence.root / bundle["state"],
            operation=operation,
            archive_reader=evidence.read,
        )
    expected = {key: anchor[key] for key in ("runId", "packageId", "planDigest", "sourceRevision")}
    expected.update(
        stateRevision=anchor["terminalRevision"],
        phase=anchor["terminalPhase"],
        manifestPath=bundle["manifest"],
        eventLog=bundle["journal"],
        planRevision=manifest["planRevision"],
        reviewerAttestationPolicy=manifest["reviewerAttestationPolicy"],
        reviewerAttestationAuthority=manifest["reviewerAttestationAuthority"],
    )
    _ensure(all(state.get(field) == value for field, value in expected.items()), "chain-state-lineage-mismatch")
    _ensure(
        require_operator_authority(state, state=True) == require_operator_authority(manifest),
        "chain-state-operator-policy-mismatch",
    )
    _ensure(state.get("packetSet", {}).get("planLockSha256") == anchor["lockSha256"], "chain-state-lock-mismatch")
    _ensure(lock["manifestHash"] == state["planDigest"], "chain-state-plan-mismatch")
    _verify_packet_set(evidence, manifest, state)
    journal = evidence.read(bundle["journal"])
    _ensure(_digest(journal) == anchor["journalSha256"], "chain-anchor-journal-mismatch")
    events = _events(journal, state)
    adopted = _object(events[0]["payload"].get("frozenPlanAuthority"), "chain-plan-authority-missing")
    _ensure(adopted.get("manifest") == manifest and adopted.get("lock") == lock, "chain-plan-authority-mismatch")
    _verify_admission_window(lock, latest=events[0]["recordedAt"])
    _verify_authorization_receipts(evidence, state, events)
    return state, events


def _events(raw: bytes, state: dict[str, Any]) -> list[dict[str, Any]]:
    _ensure(1 < state["stateRevision"] <= _MAX_FILES + 1, "chain-journal-length-mismatch")
    events = []
    found = set()
    ledger = _object(state.get("operationLedger"), "chain-state-ledger-missing")
    for revision, line in enumerate(BytesIO(raw), start=2):
        _ensure(revision <= state["stateRevision"], "chain-journal-length-mismatch")
        row = load_json_object(line, label="anchored journal event")
        op = row.get("operationId")
        if not isinstance(op, str) or not op or op in found:
            raise LifecycleError("chain-journal-operation-duplicate", "Missing or repeated operation")
        _ensure(
            row.get("schemaVersion") == "agent-workflow-event.v1" and row.get("stateRevision") == revision,
            "chain-journal-order-mismatch",
        )
        _ensure(
            row.get("packageId") == state["packageId"] and row.get("runId") == state["runId"],
            "chain-journal-lineage-mismatch",
        )
        recorded = _object(ledger.get(op), "chain-journal-operation-unbound")
        _ensure(
            recorded.get("stateRevision") == revision
            and recorded.get("eventType") == row.get("eventType")
            and recorded.get("recordedAt") == row.get("recordedAt"),
            "chain-journal-ledger-mismatch",
        )
        found.add(op)
        events.append(row)
    _ensure(len(events) == state["stateRevision"] - 1, "chain-journal-length-mismatch")
    _ensure(found == set(ledger), "chain-journal-terminal-mismatch")
    _require_supported_history(state, events)
    return events


def _require_supported_history(state: dict[str, Any], events: list[dict[str, Any]]) -> None:
    types = [event["eventType"] for event in events]
    if types.count("plan-adopted") != 1 or any(kind not in _SUPPORTED_EVENTS for kind in types):
        raise _Incomplete("chain-plan-history-unsupported", "Expected one direct strict run without extra transitions")
    snapshots = state.get("priorSnapshots", [])
    if len(snapshots) != 1 or not is_initial_snapshot_lineage(SNAPSHOT_KIND, snapshots[0]["lineage"]):
        raise _Incomplete("chain-plan-history-unsupported", "Expected only the empty initial snapshot")
    if types.count("final-audit-outcome-applied") > 1:
        raise _Incomplete("chain-outcome-history-unsupported", "Expected one accepting final outcome")
    if any(task.get("attemptHistory") or task.get("attempt", 0) > 1 for task in state["tasks"]):
        raise _Incomplete("chain-task-history-unsupported", "Expected a single attempt per selected task")
    for event in events:
        _verify_checkpoint_scope(event)
    _ensure(
        types[:3] == list(_START_EVENTS)
        and types[-2:] == list(_FINISH_EVENTS)
        and all(item in _TASK_EVENTS for item in types[3:-2]),
        "chain-journal-transition-order",
    )
    adoption = _object(events[0].get("payload"), "chain-plan-adoption-missing")
    _ensure(
        all(adoption.get(key) == state[key] for key in ("planDigest", "planRevision")),
        "chain-plan-adoption-mismatch",
    )


def _verify_checkpoint_scope(event: dict[str, Any]) -> None:
    payload = _object(event.get("payload"), "chain-journal-payload-invalid")
    checkpoint = payload.get("contextCheckpoint")
    if checkpoint is None:
        return
    if not isinstance(checkpoint, dict) or checkpoint.get("status") != "SKIPPED" or checkpoint.get("required"):
        raise _Incomplete("chain-checkpoint-history-unsupported", "Selected run requires checkpoint evidence")
    _ensure(
        checkpoint.get("eventType") == event["eventType"]
        and checkpoint.get("operationId") == event["operationId"]
        and all(checkpoint.get(key) is None for key in ("checkpointPath", "checkpointEvent", "checkpointDigest")),
        "chain-checkpoint-scope-mismatch",
    )


def _verify_packet_set(evidence: _Snapshot, manifest: dict[str, Any], state: dict[str, Any]) -> None:
    path, index = evidence.identity(state.get("packetSet"))
    artifact_root = manifest["package"]["artifactRoot"]
    expected_directory = f"{artifact_root}/workflow/task-packets"
    _ensure(path == f"{expected_directory}/index.json", "chain-packet-set-path")
    _ensure(
        index.get("packageId") == state["packageId"]
        and index.get("manifestDigest") == state["planDigest"]
        and index.get("outputDirectory") == expected_directory,
        "chain-packet-set-lineage",
    )
    tasks = state["tasks"]
    packets = index.get("packets")
    records = _records_by_task(packets)
    planned_tasks = {item["id"]: item for item in manifest["workstreams"]}
    _ensure(
        index.get("packetCount") == len(tasks) == len(records) == len(planned_tasks),
        "chain-packet-count",
    )
    packet_digests = {}
    for task in tasks:
        planned = planned_tasks[task["id"]]
        record = _object(task.get("packet"), "chain-packet-identity-missing")
        _ensure(record == records.get(task["id"]), "chain-packet-inventory")
        _ensure(
            task["id"] == planned["id"] == record["taskId"]
            and task.get("required", True) == planned.get("required", True)
            and task["dependsOn"] == planned.get("dependsOn", []) == record["dependsOn"],
            "chain-task-plan-binding",
        )
        _ensure(record["path"] == f"{expected_directory}/{task['id']}.task-packet.json", "chain-packet-path")
        _, packet = evidence.identity(record)
        _ensure(
            packet["task"]["id"] == task["id"] and packet["plan"]["planDigest"] == state["planDigest"],
            "chain-packet-lineage",
        )
        packet_digests[task["id"]] = record["sha256"]
    _ensure(
        index["packetSetHash"] == state["packetSet"]["packetSetHash"] == canonical_digest({"packets": packet_digests}),
        "chain-packet-set-digest",
    )


def _records_by_task(packets: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(packets, list):
        raise LifecycleError("chain-packet-inventory", "Packet index requires an array")
    result: dict[str, dict[str, Any]] = {}
    for raw in packets:
        value = _object(raw, "chain-packet-inventory")
        key = value.get("taskId")
        if not isinstance(key, str) or key in result:
            raise LifecycleError("chain-packet-inventory", "Duplicate or invalid packet task")
        result[key] = value
    return result


def _verify_chain_artifacts(
    evidence: _Snapshot, bundle: dict[str, Any], anchor: dict[str, Any], state: dict[str, Any], bundle_path: str
) -> None:
    required = set(evidence.files) - {bundle_path}
    raw = evidence.read(bundle["chain"])
    _ensure(_digest(raw) == anchor["chainSha256"], "chain-anchor-receipts-mismatch")
    chain = load_json_object(raw, label="anchored receipt chain")
    entries = chain.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_FILES:
        raise LifecycleError("chain-receipt-count", "Receipt inventory is missing or out of bounds")
    result = validate_receipt_hash_chain(chain)
    if result["status"] != "PASS":
        raise LifecycleError(result["blockers"][0]["code"], "Invalid receipt link")
    _ensure(chain.get("lineage") == {key: state[key] for key in _LINEAGE}, "chain-receipt-lineage")
    artifact_digests = {}
    for entry in entries:
        artifact = entry["artifact"]
        path = artifact["path"]
        _ensure(path not in artifact_digests, "chain-receipt-alias")
        artifact_digests[path] = artifact["digest"]
    _ensure(required == set(artifact_digests), "chain-receipt-membership-mismatch")
    for path, digest in artifact_digests.items():
        _ensure(_digest(evidence.files[path]) == digest, "chain-receipt-artifact-mismatch")


def _verify_reviewer_receipts(
    evidence: _Snapshot,
    manifest: dict[str, Any],
    state: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    _verify_task_reviews(evidence, manifest, state, events)
    _, report = evidence.identity(state.get("finalAudit"))
    _, proof = evidence.identity(state.get("finalProof"))
    outcome = _object(state.get("finalAuditOutcome"), "chain-final-outcome-missing")
    final = _object(events[-1].get("payload"), "chain-final-event-missing")
    _require_absent_profile_data(
        final,
        (
            "completionCheckReceipt",
            "completionGate",
            "finalizationGateReceipts",
            "followUpRegister",
            "goalRecord",
            "lifecycleControlStop",
            "releaseFullValidation",
            "reviewMeshQuorum",
        ),
    )
    _ensure(
        outcome.get("verdict") == "ACCEPTED" and outcome.get("finalAudit") == state["finalAudit"],
        "chain-final-outcome-mismatch",
    )
    _verify_outcome_event(report, state, outcome, events[-2])
    _ensure(final.get("finalAudit") == state["finalAudit"] == proof.get("finalAudit"), "chain-final-review-mismatch")
    _ensure(final.get("proof") == state["finalProof"], "chain-final-proof-mismatch")
    _verify_terminal_proof(proof, state, events[-1])
    _final_attestation(
        manifest,
        state,
        report,
        state["finalAudit"],
        "final-audit",
        earliest=events[-3]["recordedAt"],
        latest=events[-2]["recordedAt"],
    )
    _verify_final_implementation_receipt(
        evidence,
        manifest,
        state,
        final,
        proof,
        earliest=events[-2]["recordedAt"],
        latest=events[-1]["recordedAt"],
    )
    integrity = proof.get("proofIntegrity")
    receipt = evidence.identity(integrity["receipt"])[1] if isinstance(integrity, dict) else None
    validate_final_proof_integrity(state=state, final_audit=report, receipt=receipt, final_proof=proof)


def _verify_final_implementation_receipt(
    evidence: _Snapshot,
    manifest: dict[str, Any],
    state: dict[str, Any],
    final: dict[str, Any],
    proof: dict[str, Any],
    *,
    earliest: str,
    latest: str,
) -> None:
    typed = state.get("finalImplementationAudit")
    final_typed_required = any(
        item.get("finalImplementationAuditRequired") is True
        or (
            isinstance(item.get("implementationAudit"), dict)
            and item["implementationAudit"].get("finalRequired") is True
        )
        for item in (manifest, state)
    )
    _ensure(typed is not None or not final_typed_required, "chain-final-implementation-missing")
    if typed is None:
        _ensure(
            proof.get("finalImplementationAudit") is None and final.get("finalImplementationAudit") is None,
            "chain-final-implementation-mismatch",
        )
        return
    typed_proof = _object(proof.get("finalImplementationAudit"), "chain-final-implementation-missing")
    identity = _object(typed, "chain-final-implementation-missing")
    _ensure(
        typed_proof == final.get("finalImplementationAudit") and typed_proof.get("audit") == identity,
        "chain-final-implementation-mismatch",
    )
    _, typed_report = evidence.identity(identity)
    _verify_final_implementation(typed_report, state)
    _final_attestation(
        manifest,
        state,
        typed_report,
        identity,
        "final-implementation-audit",
        earliest=earliest,
        latest=latest,
    )


def _verify_terminal_proof(proof: dict[str, Any], state: dict[str, Any], event: dict[str, Any]) -> None:
    _ensure(
        proof.get("schemaVersion") == "agent-run-final-proof.v1"
        and proof.get("semanticStatus") == state["finalProof"].get("semanticStatus") == "READY_FOR_FINALIZATION"
        and proof.get("productionPromotionClaimed") is False
        and proof.get("operationId") == event["operationId"]
        and proof.get("stateRevisionBeforeFinalization") == state["stateRevision"] - 1,
        "chain-final-proof-revision-mismatch",
    )
    _ensure(
        proof.get("bodyDigest") == canonical_digest({k: v for k, v in proof.items() if k != "bodyDigest"}),
        "chain-final-proof-digest-mismatch",
    )
    _ensure(all(proof.get(key) == state[key] for key in _LINEAGE), "chain-final-proof-lineage")
    actual_tasks = proof.get("acceptedTasks")
    _ensure(
        isinstance(actual_tasks, list)
        and all(isinstance(task, dict) for task in actual_tasks)
        and [{key: task.get(key) for key in ("id", "attempt", "review")} for task in actual_tasks]
        == [
            {key: task.get(key) for key in ("id", "attempt", "review")}
            for task in state["tasks"]
            if task["status"] == "ACCEPTED"
        ],
        "chain-proof-task-inventory-mismatch",
    )


def _verify_final_implementation(report: dict[str, Any], state: dict[str, Any]) -> None:
    _ensure(
        validate_final_implementation_audit(report, state=state)["status"] == "PASS",
        "chain-final-implementation-not-accepted",
    )
    task_audits = {
        task["id"]: task["implementationAuditReport"]
        for task in state["tasks"]
        if task["status"] == "ACCEPTED" and "implementationAuditReport" in task
    }
    inventory = _records_by_task(report.get("reports"))
    _ensure(
        inventory.keys() == task_audits.keys() and report.get("missingTaskIds") == [],
        "chain-final-implementation-inventory",
    )
    for task_id, identity in task_audits.items():
        item = inventory[task_id]
        _ensure(
            all(item.get(key) == identity.get(key) for key in ("path", "sha256", "bytes"))
            and item.get("attempt") == identity.get("attempt")
            and item.get("verdict") == identity.get("verdict") == "ACCEPTED",
            "chain-final-implementation-task-identity",
        )


def _verify_outcome_event(
    report: dict[str, Any], state: dict[str, Any], outcome: dict[str, Any], event: dict[str, Any]
) -> None:
    payload = _object(event.get("payload"), "chain-final-outcome-event-missing")
    scope = ("verdict", "taskIds", "findingIds")
    _ensure(
        all(payload.get(field) == outcome[field] for field in (*scope, "finalAudit")),
        "chain-final-outcome-event-mismatch",
    )
    _ensure(all(report.get(field) == outcome[field] for field in scope), "chain-final-signed-scope-mismatch")
    validation = validate_final_audit_outcome_report(
        report, state=state, verdict=outcome["verdict"], task_ids=outcome["taskIds"], finding_ids=outcome["findingIds"]
    )
    _ensure(validation["status"] == "PASS", "chain-final-outcome-invalid")
    _ensure(
        report.get("schemaVersion") in {"agent-final-candidate-audit.v1", "agent-run-final-audit.v1"}
        and not report.get("notAcceptedTasks")
        and not report.get("missingReleaseEvidence")
        and not open_blocking_finding_ids(report["findings"]),
        "chain-final-audit-incomplete",
    )
    validate_completion_signal(
        _object(report.get("completionSignal"), "chain-final-completion-signal-missing"), state=state
    )
    _ensure(
        outcome.get("outcomeDigest")
        == canonical_digest({name: value for name, value in outcome.items() if name != "outcomeDigest"}),
        "chain-final-outcome-digest-mismatch",
    )


def _verify_admission_window(receipt: dict[str, Any], *, latest: str, earliest: str | None = None) -> dict[str, Any]:
    admission = _object(receipt.get("reviewerAdmission"), "chain-reviewer-admission-missing")
    observed = parse_reviewer_utc(admission.get("observedAt"))
    _ensure(
        observed <= parse_reviewer_utc(latest) and (earliest is None or parse_reviewer_utc(earliest) <= observed),
        "chain-reviewer-admission-outside-journal-window",
    )
    return admission


def _final_attestation(
    manifest: dict[str, Any],
    state: dict[str, Any],
    report: dict[str, Any],
    identity: dict[str, Any],
    phase: str,
    *,
    earliest: str,
    latest: str,
) -> None:
    archived = _verify_admission_window(identity, earliest=earliest, latest=latest)
    _ensure(
        final_reviewer_decision_from_manifest(state, manifest, report, phase=phase, archived=archived) == archived,
        "chain-final-attestation-mismatch",
    )


def _verify_task_reviews(
    evidence: _Snapshot, manifest: dict[str, Any], state: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    tasks = {task["id"]: task for task in state["tasks"] if task["status"] == "ACCEPTED"}
    _ensure(
        all(not task.get("required", True) or task["id"] in tasks for task in state["tasks"]),
        "chain-required-task-missing",
    )
    _task_events(tasks, state, events)
    workstreams = {item["id"]: item for item in manifest["workstreams"]}
    for task_id, task in tasks.items():
        _verify_task_reports(evidence, manifest, state, task, workstreams[task_id])


def _task_events(tasks: dict[str, dict[str, Any]], state: dict[str, Any], events: list[dict[str, Any]]) -> None:
    indices: dict[str, int] = {}
    committed_at: dict[str, str] = {}
    accepted: set[str] = set()
    for event in events[3:-2]:
        payload = _object(event.get("payload"), "chain-task-event-missing")
        task_id = payload["taskId"]
        if payload.get("attempt") != 1:
            raise _Incomplete("chain-task-history-unsupported", "Expected a single attempt per selected task")
        task = _object(tasks.get(task_id), "chain-task-event-unexpected")
        index = indices.get(task_id, 0)
        _ensure(index < len(_TASK_EVENTS) and event["eventType"] == _TASK_EVENTS[index], "chain-task-event-order")
        if index == 0:
            _ensure(
                payload.get("planDigest") == state["planDigest"]
                and payload.get("sourceRevision") == state["sourceRevision"]
                and set(task["dependsOn"]) <= accepted,
                "chain-task-start-binding",
            )
            _require_absent_profile_data(payload, ("immutableInputAdmission", "executionStrategy"))
        elif index == 1:
            _ensure(payload.get("result") == task["result"], "chain-task-result-mismatch")
            _require_absent_profile_data(payload, ("modelUsageReceipt",))
            committed_at[task_id] = event["recordedAt"]
        else:
            _ensure(payload.get("review") == task["review"], "chain-task-acceptance-mismatch")
            earliest, latest = committed_at[task_id], event["recordedAt"]
            _verify_admission_window(task["review"], earliest=earliest, latest=latest)
            typed = task.get("implementationAuditReport")
            if typed is not None:
                _verify_admission_window(typed, earliest=earliest, latest=latest)
            accepted.add(task_id)
        indices[task_id] = index + 1
    _ensure(accepted == tasks.keys(), "chain-task-acceptance-incomplete")


def _verify_task_reports(
    evidence: _Snapshot,
    manifest: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    workstream: dict[str, Any],
) -> None:
    result_identity = _object(task.get("result"), "chain-task-result-missing")
    _, result = evidence.identity(result_identity)
    validate_archived_task_result(state, task, result)
    _, report = evidence.identity(task.get("review"))
    archived = _object(task["review"].get("reviewerAdmission"), "chain-reviewer-admission-missing")
    validate_archived_task_review(state, task, report, result, archived=archived)
    _ensure(report["verdict"] == task["review"].get("verdict"), "chain-task-review-effect")
    typed = task.get("implementationAuditReport")
    _ensure(typed is not None or not _typed_required(manifest, state, task, workstream), "chain-task-audit-missing")
    if typed is not None:
        _, audit = evidence.identity(typed)
        if audit.get("schemaVersion") != "agent-implementation-audit-report.v1":
            raise _Incomplete("chain-task-audit-profile-unsupported", "Expected ordinary typed implementation audit")
        require_implementation_audit_accepted(
            validate_implementation_audit_report(audit, state=state, task=task), audit
        )
        archived = _object(typed.get("reviewerAdmission"), "chain-reviewer-admission-missing")
        _ensure(
            task_reviewer_decision(state, task, audit, result, phase="implementation-audit", archived=archived)
            == archived,
            "chain-task-audit-attestation-mismatch",
        )


def _typed_required(*sources: dict[str, Any]) -> bool:
    return any(
        item.get("implementationAuditRequired") is True
        or (isinstance(item.get("implementationAudit"), dict) and item["implementationAudit"].get("required") is True)
        for item in sources
    )


def _require_absent_profile_data(value: dict[str, Any], keys: tuple[str, ...]) -> None:
    if any(value.get(key) for key in keys):
        raise _Incomplete("chain-additional-admission-unsupported", "The selected history needs extra receipt checks")


def _verify_authorization_receipts(evidence: _Snapshot, state: dict[str, Any], events: list[dict[str, Any]]) -> None:
    row = events[1]
    payload = _object(row.get("payload"), "chain-authorization-event-missing")
    _, receipt = evidence.identity(payload.get("authorizationReceipt"))
    before = {**state, "stateRevision": row["stateRevision"] - 1}
    now = parse_reviewer_utc(row["recordedAt"])
    _ensure(parse_reviewer_utc(events[0]["recordedAt"]) <= now, "chain-execution-time-order")
    validation = validate_workflow_authorization_receipt(receipt, state=before, now=now)
    issued = datetime.fromisoformat(receipt["issuedAt"].replace("Z", "+00:00")).astimezone(UTC)
    _ensure(issued.replace(microsecond=0) <= now, "chain-authorization-issued-after-grant")
    _verify_execution_window(events[2:], authorized_at=now, expires_at=validation["expiresAt"])
    terminal = state["authorization"]
    _ensure(
        terminal.get("authorizationReceipt") == payload.get("authorizationReceipt")
        and terminal.get("granted") is True
        and terminal.get("grantedBy") == validation["authorizedBy"]
        and terminal.get("expiresAt") == validation["expiresAt"],
        "chain-authorization-terminal-mismatch",
    )


def _verify_execution_window(events: list[dict[str, Any]], *, authorized_at: datetime, expires_at: str) -> None:
    payload = _object(events[0].get("payload"), "chain-journal-payload-invalid")
    _ensure(
        payload.get("previousPhase") == "READY" and payload.get("phase") == "RUNNING",
        "chain-execution-start-transition",
    )
    deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    previous = authorized_at
    for event in events:
        current = parse_reviewer_utc(event["recordedAt"])
        _ensure(previous <= current, "chain-execution-time-order")
        _ensure(current < deadline, "authorization-expired")
        if current + timedelta(microseconds=999_999) >= deadline:
            raise _Incomplete("chain-authorization-time-precision", "Archived event time straddles the grant expiry")
        previous = current


def _verify_operator_receipts(
    evidence: _Snapshot,
    bundle: dict[str, Any],
    manifest: dict[str, Any],
    lock: dict[str, Any],
    state: dict[str, Any],
    events: list[dict[str, Any]],
) -> bool:
    policy = require_operator_authority(manifest)
    if policy is None:
        return False
    if policy["mode"] != "required":
        raise _Incomplete("chain-advisory-operator-not-checked", "Advisory signatures do not bind native admission")
    signature = (Path(bundle["lock"]).parent / FREEZE_SIGNATURE_NAME).as_posix()
    _signature(
        evidence,
        signature,
        policy,
        expected_operator_decision(manifest, "freeze"),
        lock["reviewerAdmission"]["observedAt"],
        lock.get("operatorSignature"),
    )
    event = events[1]
    payload = _object(event.get("payload"), "chain-authorization-event-missing")
    subject_path, receipt = evidence.identity(payload.get("authorizationReceipt"))
    before = {**state, "stateRevision": event["stateRevision"] - 1}
    expected = expected_operator_decision(before, "authorize", operation_id=event["operationId"], subject=receipt)
    _ensure(
        state["authorization"].get("operatorSignature") == payload.get("operatorSignature"),
        "chain-operator-authorization-terminal",
    )
    _signature(
        evidence,
        subject_path + ".operator-signature.json",
        policy,
        expected,
        event["recordedAt"],
        payload.get("operatorSignature"),
    )
    terminal = events[-1]
    final_path, audit = evidence.identity(state["finalAudit"])
    _, proof = evidence.identity(state["finalProof"])
    before = {**state, "stateRevision": terminal["stateRevision"] - 1}
    expected = expected_operator_decision(before, "accept", operation_id=terminal["operationId"], subject=audit)
    _signature(
        evidence,
        final_path + ".operator-signature.json",
        policy,
        expected,
        terminal["recordedAt"],
        proof.get("operatorSignature"),
    )
    return True


def _signature(
    evidence: _Snapshot,
    path: str,
    policy: dict[str, Any],
    expected: dict[str, Any],
    observed_at: str,
    admitted: Any,
) -> None:
    raw = evidence.read(path)
    envelope = load_json_object(raw, label="operator signature")
    try:
        valid_from, expires = operator_interval(validate_operator_envelope(envelope)["payload"])
    except LifecycleError as exc:
        raise LifecycleError("chain-operator-signature-mismatch", "Operator envelope is invalid") from exc
    probe, whole_second = _operator_observation_sample(parse_reviewer_utc(observed_at), valid_from, expires)
    result = verify_operator_envelope(policy, envelope, expected, observed_at=probe.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    result["artifact"] = {"path": path, "bytes": len(raw), "sha256": _digest(raw)}
    _ensure(result["signatureVerified"] is True and result == admitted, "chain-operator-signature-mismatch")
    if not whole_second:
        raise _Incomplete("chain-operator-time-precision", "Archived time does not establish exact key validity")


def _operator_observation_sample(start: datetime, valid_from: datetime, expires: datetime) -> tuple[datetime, bool]:
    end = start + timedelta(microseconds=999_999)
    sample = max(start, valid_from)
    _ensure(sample <= end and sample < expires, "chain-operator-signature-mismatch")
    return sample, valid_from <= start and end < expires
