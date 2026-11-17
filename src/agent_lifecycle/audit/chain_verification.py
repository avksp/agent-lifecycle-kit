"""Read-only recomputation of one independently anchored native run."""

from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from itertools import islice
from pathlib import Path
from typing import Any

from agent_lifecycle.audit.proof_chain import validate_receipt_hash_chain
from agent_lifecycle.contracts.authority_io import open_authority_read
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.chain_verification_schemas import ANCHOR, BUNDLE, REPORT, TRUST, validate_chain_input
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.operator_signature import (
    FREEZE_SIGNATURE_NAME,
    expected_operator_decision,
    verify_operator_envelope,
)
from agent_lifecycle.contracts.operator_signature_schemas import require_operator_authority
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.reviewer_identity_schemas import (
    REVIEWER_REQUIRED_LOCK,
    REVIEWER_REQUIRED_STATE,
    parse_reviewer_utc,
)
from agent_lifecycle.contracts.workflow_state_authority import decode_workflow_authority
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from agent_lifecycle.freeze.package_integrity import (
    _reject_undeclared_top_level_files,
    _verify_locked_reviewer_admission,
    verify_plan_lock_envelope,
)
from agent_lifecycle.workflow.final_proof_integrity import validate_final_proof_integrity
from agent_lifecycle.workflow.reviewer_gate import final_reviewer_decision, task_reviewer_decision

_MAX_FILES = 1024
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 64 * 1024 * 1024
_AUTHORIZATION_EVENTS = {"execution-authorized", "execution-authorization-renewed"}
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
    with open_authority_read(path, root=root) as handle:
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

    def object(self, path: str) -> dict[str, Any]:
        return load_json_object(self.read(path), label="chain evidence")

    def identity(self, summary: Any) -> tuple[str, dict[str, Any]]:
        selected = _object(summary, "chain-artifact-identity-missing")
        path = selected.get("path")
        if not isinstance(path, str):
            raise LifecycleError("chain-artifact-path-missing", "Expected a receipt path")
        raw = self.read(path)
        data = load_json_object(raw, label="native receipt")
        _ensure(raw == canonical_bytes(data) + b"\n" and len(raw) == selected.get("bytes"),
                "chain-artifact-bytes-mismatch")
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
        _ensure(root.resolve(strict=True) == root, "chain-evidence-root-not-canonical")
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

        phase = "receipt-chain"
        chain_paths = _verify_chain_artifacts(snapshot, bundle, anchor, state)
        checks.append({"check": phase, "status": "VERIFIED"})

        phase = "reviewer-signatures"
        _verify_reviewer_receipts(snapshot, bundle, manifest, state, events)
        checks.append({"check": phase, "status": "VERIFIED"})

        phase = "operator-signatures"
        applicable = _verify_operator_receipts(snapshot, bundle, manifest, lock, state, events)
        checks.append({"check": phase, "status": "VERIFIED" if applicable else "NOT_APPLICABLE"})

        phase = "receipt-membership"
        required = set(snapshot.files) - {bundle_path, bundle["chain"]}
        _ensure(required == chain_paths, "chain-receipt-membership-mismatch")
        checks.append({"check": phase, "status": "VERIFIED"})
        phase = "snapshot"
        for path, raw in snapshot.files.items():
            _ensure(_bounded_file(root, root / path, len(raw)) == raw, "chain-input-changed")
        _ensure(
            _trusted_input(root, trust_config_path) == trust_raw and _trusted_input(root, anchor_path) == anchor_raw,
            "chain-trusted-input-changed",
        )
        checks.append({"check": phase, "status": "VERIFIED"})
    except _Incomplete as exc:
        return _report("NOT_CHECKED", 1, checks, phase, exc.code)
    except LifecycleError as exc:
        return _report("INVALID_INPUT" if phase == "input" else "MISMATCH", 2 if phase == "input" else 1,
                       checks, phase, exc.code)
    except FileNotFoundError:
        return _report("INVALID_INPUT" if phase == "input" else "MISMATCH", 2 if phase == "input" else 1,
                       checks, phase, "chain-input-missing")
    except OSError:
        return _report("INVALID_INPUT", 2, checks, phase, "chain-input-unreadable")
    except (TypeError, KeyError, ValueError, RecursionError):
        return _report("INVALID_INPUT" if phase == "input" else "MISMATCH", 2 if phase == "input" else 1,
                       checks, phase, "chain-input-malformed")
    return _report("VERIFIED", 0, checks)


def _trusted_input(root: Path, path: Path) -> bytes:
    selected = path.absolute()
    _ensure(selected.resolve(strict=True) == selected, "chain-trust-path-not-canonical")
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
    _ensure(canonical_digest(manifest["reviewerAttestationPolicy"]) == trust["reviewerPolicyDigest"],
            "chain-reviewer-trust-mismatch")
    operator = require_operator_authority(manifest)
    _ensure((canonical_digest(operator) if operator else None) == trust["operatorPolicyDigest"],
            "chain-operator-trust-mismatch")
    entries = joined["entries"]
    _ensure([entry["path"] for entry in entries] == manifest["planFiles"], "chain-lock-inventory-mismatch")
    _ensure(bundle["manifest"] in manifest["planFiles"], "chain-manifest-unbound")
    for entry in entries:
        raw = evidence.read(entry["path"])
        _ensure(_digest(raw) == entry["sha256"] and len(raw) == entry["bytes"], "chain-lock-file-mismatch")
    package = evidence.root / root
    with os.scandir(package) as children:
        _ensure(len(list(islice(children, _MAX_FILES + 1))) <= _MAX_FILES, "chain-lock-directory-limit")
    _reject_undeclared_top_level_files(manifest, package, entries, repository_root=evidence.root)
    _verify_locked_reviewer_admission(manifest, lock, evidence.root, require_current=False)
    return manifest, lock


def _verify_native_state(
    evidence: _Snapshot, bundle: dict[str, Any], anchor: dict[str, Any], manifest: dict[str, Any], lock: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = evidence.read(bundle["state"])
    _ensure(_digest(raw) == anchor["stateSha256"], "chain-anchor-state-mismatch")
    body = load_json_object(raw, label="anchored state")
    if body.get("schemaVersion") != REVIEWER_REQUIRED_STATE or body.get("phase") != "COMPLETE":
        raise _Incomplete("chain-state-profile-unsupported", "Expected one terminal strict native run")
    with StorageOperation(evidence.root, state_path=evidence.root / bundle["state"]) as operation:
        state = decode_workflow_authority(raw, root=evidence.root, state_path=evidence.root / bundle["state"],
                                          operation=operation)
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
    _ensure(require_operator_authority(state, state=True) == require_operator_authority(manifest),
            "chain-state-operator-policy-mismatch")
    _ensure(state.get("packetSet", {}).get("planLockSha256") == anchor["lockSha256"], "chain-state-lock-mismatch")
    _ensure(lock["manifestHash"] == state["planDigest"], "chain-state-plan-mismatch")
    journal = evidence.read(bundle["journal"])
    _ensure(_digest(journal) == anchor["journalSha256"], "chain-anchor-journal-mismatch")
    events = _events(journal, state)
    _verify_authorization_receipts(evidence, state, events)
    return state, events


def _events(raw: bytes, state: dict[str, Any]) -> list[dict[str, Any]]:
    lines = raw.splitlines()
    _ensure(len(lines) == state["stateRevision"] - 1 and len(lines) <= _MAX_FILES, "chain-journal-length-mismatch")
    events = []
    found = set()
    ledger = _object(state.get("operationLedger"), "chain-state-ledger-missing")
    for revision, line in enumerate(lines, start=2):
        row = load_json_object(line, label="anchored journal event")
        op = row.get("operationId")
        if not isinstance(op, str) or not op or op in found:
            raise LifecycleError("chain-journal-operation-duplicate", "Missing or repeated operation")
        _ensure(row.get("schemaVersion") == "agent-workflow-event.v1" and row.get("stateRevision") == revision,
                "chain-journal-order-mismatch")
        _ensure(row.get("packageId") == state["packageId"] and row.get("runId") == state["runId"],
                "chain-journal-lineage-mismatch")
        recorded = _object(ledger.get(op), "chain-journal-operation-unbound")
        _ensure(recorded.get("stateRevision") == revision and recorded.get("eventType") == row.get("eventType"),
                "chain-journal-ledger-mismatch")
        found.add(op)
        events.append(row)
    _ensure(found == set(ledger) and events[-1]["eventType"] == "run-finalized", "chain-journal-terminal-mismatch")
    if sum(row["eventType"] == "plan-adopted" for row in events) != 1:
        raise _Incomplete("chain-plan-history-unsupported", "Expected one adopted plan")
    return events


def _verify_chain_artifacts(
    evidence: _Snapshot, bundle: dict[str, Any], anchor: dict[str, Any], state: dict[str, Any]
) -> set[str]:
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
    paths = set()
    for entry in entries:
        artifact = entry["artifact"]
        path = artifact["path"]
        _ensure(path not in paths and path != bundle["chain"], "chain-receipt-alias")
        _ensure(_digest(evidence.read(path)) == artifact["digest"], "chain-receipt-artifact-mismatch")
        paths.add(path)
    return paths


def _verify_reviewer_receipts(
    evidence: _Snapshot, bundle: dict[str, Any], manifest: dict[str, Any],
    state: dict[str, Any], events: list[dict[str, Any]],
) -> None:
    state_path = evidence.root / bundle["state"]
    implementation = manifest.get("implementationAudit")
    policy = implementation if isinstance(implementation, dict) else {}
    _verify_task_reviews(evidence, state, events, typed_required=policy.get("required") is True)
    _, report = evidence.identity(state.get("finalAudit"))
    _, proof = evidence.identity(state.get("finalProof"))
    outcome = _object(state.get("finalAuditOutcome"), "chain-final-outcome-missing")
    final = _object(events[-1].get("payload"), "chain-final-event-missing")
    _ensure(outcome.get("verdict") == "ACCEPTED" and outcome.get("finalAudit") == state["finalAudit"],
            "chain-final-outcome-mismatch")
    _verify_outcome_event(outcome, events)
    _ensure(final.get("finalAudit") == state["finalAudit"] == proof.get("finalAudit"), "chain-final-review-mismatch")
    _ensure(final.get("proof") == state["finalProof"], "chain-final-proof-mismatch")
    _ensure(proof.get("operationId") == events[-1]["operationId"] and
            proof.get("stateRevisionBeforeFinalization") == state["stateRevision"] - 1,
            "chain-final-proof-revision-mismatch")
    _ensure(proof.get("bodyDigest") == canonical_digest({k: v for k, v in proof.items() if k != "bodyDigest"}),
            "chain-final-proof-digest-mismatch")
    _ensure(all(proof.get(key) == state[key] for key in _LINEAGE), "chain-final-proof-lineage")
    actual_tasks = proof.get("acceptedTasks")
    _ensure(isinstance(actual_tasks, list) and [
        {key: task.get(key) for key in ("id", "attempt", "review")} for task in actual_tasks
    ] == [
        {key: task.get(key) for key in ("id", "attempt", "review")}
        for task in state["tasks"] if task["status"] == "ACCEPTED"
    ], "chain-proof-task-inventory-mismatch")
    _final_attestation(state_path, state, report, state["finalAudit"], "final-audit")
    typed = state.get("finalImplementationAudit")
    _ensure(typed is not None or policy.get("finalRequired") is not True, "chain-final-implementation-missing")
    if typed is not None:
        typed_proof = _object(proof.get("finalImplementationAudit"), "chain-final-implementation-missing")
        identity = _object(typed, "chain-final-implementation-missing")
        _ensure(typed_proof == final.get("finalImplementationAudit") and typed_proof.get("audit") == identity,
                "chain-final-implementation-mismatch")
        _, typed_report = evidence.identity(identity)
        _final_attestation(state_path, state, typed_report, identity, "final-implementation-audit")
    integrity = proof.get("proofIntegrity")
    receipt = evidence.identity(integrity["receipt"])[1] if isinstance(integrity, dict) else None
    validate_final_proof_integrity(state=state, final_audit=report, receipt=receipt, final_proof=proof)


def _verify_outcome_event(outcome: dict[str, Any], events: list[dict[str, Any]]) -> None:
    observed = [event for event in events if event.get("eventType") == "final-audit-outcome-applied"]
    if len(observed) != 1:
        raise _Incomplete("chain-outcome-history-unsupported", "Expected exactly one final outcome")
    payload = _object(observed[0].get("payload"), "chain-final-outcome-event-missing")
    _ensure(all(payload.get(field) == outcome[field] for field in ("verdict", "finalAudit", "taskIds", "findingIds")),
            "chain-final-outcome-event-mismatch")
    _ensure(outcome.get("outcomeDigest") == canonical_digest(
        {name: value for name, value in outcome.items() if name != "outcomeDigest"}
    ), "chain-final-outcome-digest-mismatch")


def _final_attestation(
    state_path: Path, state: dict[str, Any], report: dict[str, Any], identity: dict[str, Any], phase: str
) -> None:
    archived = _object(identity.get("reviewerAdmission"), "chain-reviewer-admission-missing")
    _ensure(final_reviewer_decision(state_path, state, report, phase=phase, archived=archived) == archived,
            "chain-final-attestation-mismatch")


def _verify_task_reviews(
    evidence: _Snapshot, state: dict[str, Any], events: list[dict[str, Any]], *, typed_required: bool
) -> None:
    accepted = {}
    results = {}
    for event in events:
        if event.get("eventType") == "task-accepted":
            payload = _object(event.get("payload"), "chain-task-event-missing")
            _ensure(payload["taskId"] not in accepted, "chain-task-accepted-duplicate")
            accepted[payload["taskId"]] = payload
        if event.get("eventType") == "task-result-committed":
            payload = _object(event.get("payload"), "chain-task-result-event-missing")
            _ensure(payload["taskId"] not in results, "chain-task-result-duplicate")
            results[payload["taskId"]] = payload
    for task in state["tasks"]:
        if task.get("attemptHistory") or task.get("attempt", 0) > 1:
            raise _Incomplete("chain-task-history-unsupported", "Archived admissions are required for selected history")
        if task.get("status") != "ACCEPTED":
            if task.get("required", True):
                raise LifecycleError("chain-required-task-missing", "Terminal state has an unaccepted required task")
            continue
        event = _object(accepted.pop(task["id"], None), "chain-task-acceptance-unbound")
        _ensure(event.get("attempt") == task["attempt"] and event.get("review") == task["review"],
                "chain-task-acceptance-mismatch")
        commit = _object(results.get(task["id"]), "chain-task-result-unbound")
        _ensure(commit.get("result") == task["result"] and commit.get("attempt") == task["attempt"],
                "chain-task-result-mismatch")
        _, result = evidence.identity(task.get("result"))
        _, report = evidence.identity(task.get("review"))
        archived = _object(task["review"].get("reviewerAdmission"), "chain-reviewer-admission-missing")
        _ensure(task_reviewer_decision(state, task, report, result, phase="task-review", archived=archived) == archived,
                "chain-task-attestation-mismatch")
        typed = task.get("implementationAuditReport")
        _ensure(typed is not None or not typed_required, "chain-task-audit-missing")
        if typed is not None:
            _, audit = evidence.identity(typed)
            archived = _object(typed.get("reviewerAdmission"), "chain-reviewer-admission-missing")
            _ensure(task_reviewer_decision(state, task, audit, result, phase="implementation-audit",
                                           archived=archived) == archived, "chain-task-audit-attestation-mismatch")
    _ensure(not accepted, "chain-task-acceptance-extra")


def _verify_authorization_receipts(
    evidence: _Snapshot, state: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    auth = [row for row in events if row.get("eventType") in _AUTHORIZATION_EVENTS]
    _ensure(bool(auth) and auth[0]["eventType"] == "execution-authorized" and
            sum(row["eventType"] == "execution-authorized" for row in auth) == 1,
            "chain-authorization-history-mismatch")
    for row in auth:
        payload = _object(row.get("payload"), "chain-authorization-event-missing")
        _, receipt = evidence.identity(payload.get("authorizationReceipt"))
        _ensure(all(receipt.get(key) == state[key] for key in _LINEAGE), "chain-authorization-lineage")
        _ensure(receipt.get("decision") == "ALLOW" and receipt.get("status") == "PASS",
                "chain-authorization-decision")
    _ensure(state["authorization"].get("authorizationReceipt") == auth[-1]["payload"].get("authorizationReceipt"),
            "chain-authorization-terminal-mismatch")


def _verify_operator_receipts(
    evidence: _Snapshot, bundle: dict[str, Any], manifest: dict[str, Any], lock: dict[str, Any],
    state: dict[str, Any], events: list[dict[str, Any]],
) -> bool:
    policy = require_operator_authority(manifest)
    if policy is None:
        return False
    if policy["mode"] != "required":
        raise _Incomplete("chain-advisory-operator-not-checked", "Advisory signatures do not bind native admission")
    signature = (Path(bundle["lock"]).parent / FREEZE_SIGNATURE_NAME).as_posix()
    _signature(evidence, signature, policy, expected_operator_decision(manifest, "freeze"),
               lock["reviewerAdmission"]["observedAt"], lock.get("operatorSignature"))
    for event in events:
        if event.get("eventType") not in _AUTHORIZATION_EVENTS:
            continue
        payload = _object(event.get("payload"), "chain-authorization-event-missing")
        subject_path, receipt = evidence.identity(payload.get("authorizationReceipt"))
        before = {**state, "stateRevision": event["stateRevision"] - 1}
        expected = expected_operator_decision(before, "authorize", operation_id=event["operationId"], subject=receipt)
        _signature(evidence, subject_path + ".operator-signature.json", policy, expected,
                   event["recordedAt"], payload.get("operatorSignature"))
    terminal = events[-1]
    final_path, audit = evidence.identity(state["finalAudit"])
    _, proof = evidence.identity(state["finalProof"])
    before = {**state, "stateRevision": terminal["stateRevision"] - 1}
    expected = expected_operator_decision(before, "accept", operation_id=terminal["operationId"], subject=audit)
    _signature(evidence, final_path + ".operator-signature.json", policy, expected,
               terminal["recordedAt"], proof.get("operatorSignature"))
    return True


def _signature(
    evidence: _Snapshot, path: str, policy: dict[str, Any], expected: dict[str, Any],
    observed_at: str, admitted: Any,
) -> None:
    raw = evidence.read(path)
    envelope = load_json_object(raw, label="operator signature")
    # Native journal and reviewer lock observations have second precision.
    # Require validity across the complete observed second.
    start = parse_reviewer_utc(observed_at)
    end = start + timedelta(microseconds=999_999)
    result = verify_operator_envelope(
        policy, envelope, expected, observed_at=start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )
    end_result = verify_operator_envelope(
        policy, envelope, expected, observed_at=end.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )
    if result["signatureVerified"] != end_result["signatureVerified"]:
        raise _Incomplete("chain-operator-time-precision", "Archived time does not establish exact key validity")
    result["artifact"] = {"path": path, "bytes": len(raw), "sha256": _digest(raw)}
    _ensure(result["signatureVerified"] is True and result == admitted, "chain-operator-signature-mismatch")
