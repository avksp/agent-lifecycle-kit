"""Checked historical native qualification inputs; no generic route support.

The constructor is an in-process value, never evidence of authority. The
collector reloads the actual frozen profile and lock before using these values.
Legacy producer helpers retain their original pins and independent review gate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.accounting.host_bridge import ARTIFACT_BYTES, BoundedReader
from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object
from agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity

ROLES = ("worker", "validator", "auditor", "retry", "coordinator", "closing")
POLARITIES = ("POSITIVE", "PRELAUNCH_REFUSAL", "STARTED_FAILURE", "STRONG_REFUSAL")
ROUTE = "codex-exact-prompt-v1"
CLAIM = "ALK_CONTROLLED_OUTBOUND_INPUT_FIT"
ADMISSION_PATH = "work/release-2-16/native-qualification-admission.json"
CAPACITY_OBLIGATION = "accounting.native.aggregate-104-105-selected-invocation-capacity"
PRODUCERS = (
    "src/agent_lifecycle/adapter_sessions/limited_native_evidence.py",
    "src/agent_lifecycle/adapter_sessions/launch_preflight.py",
    "tests/adapter_sessions/codex_limited_native_support.py",
    "tests/adapter_sessions/test_codex_exact_prompt.py",
)
LEGACY_MANIFEST_PATH = "tasks/release-2-16/plan.manifest.json"
LEGACY_LOCK_PATH = "tasks/release-2-16/plan.lock.json"
LEGACY_CONTRACT_PATH = "tasks/release-2-16/route-bootstrap-contract.json"
LEGACY_REVIEW_ROOT = "work/release-2-16/evidence/ordinary-audit/"


@dataclass(frozen=True)
class QualificationContext:
    manifest_digest: str
    lock_sha256: str
    profile_sha256: str
    admission_path: str
    route_id: str
    claim: str
    rows: tuple[dict[str, Any], ...]
    producer_paths: tuple[str, ...]


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise LifecycleError("limited-native-evidence-unavailable", detail)


def _validate_registered_profile(profile: dict[str, Any]) -> None:
    """Only the historically reviewed limited profile has a registered route."""
    evidence = profile["evidenceContract"]
    _require(
        profile["schemaVersion"] == "alk-r69-limited-native-matrix.v1"
        and profile["claim"] == CLAIM
        and tuple(profile["roles"]) == ROLES
        and evidence["admissionPath"] == ADMISSION_PATH
        and tuple(evidence["producerSources"]) == PRODUCERS,
        "Unregistered native qualification profile",
    )
    rows = profile["rows"]
    _require(
        profile["caseCount"] == len(rows) == 24
        and {(r["role"], r["polarity"]) for r in rows} == {(r, p) for r in ROLES for p in POLARITIES}
        and len({r["caseId"] for r in rows}) == 24,
        "Exact native24 inventory required",
    )


def load_qualification_context(root: Path, reader: BoundedReader, *, manifest: dict[str, Any]) -> QualificationContext:
    """Independently reopen the sole registered frozen qualification profile."""
    actual = load_json_object(reader.read(root, LEGACY_MANIFEST_PATH, ARTIFACT_BYTES), label="frozen native manifest")
    lock_raw = reader.read(root, LEGACY_LOCK_PATH, ARTIFACT_BYTES)
    lock = load_json_object(lock_raw, label="frozen native lock")
    _require(
        manifest.get("status") == "FROZEN"
        and manifest.get("package", {}).get("id") == "release-2-16"
        and canonical_digest(actual) == canonical_digest(manifest),
        "Current registered frozen qualification plan required",
    )
    verify_plan_package_integrity(actual, lock, repository_root=root)
    profile_raw = reader.read(root, LEGACY_CONTRACT_PATH, ARTIFACT_BYTES)
    profile_sha256 = hashlib.sha256(profile_raw).hexdigest()
    reference = {
        "path": LEGACY_CONTRACT_PATH,
        "bytes": len(profile_raw),
        "sha256": profile_sha256,
    }
    _require(
        LEGACY_CONTRACT_PATH in actual["planFiles"] and reference in lock["entries"],
        "Native qualification profile is outside the exact frozen inventory",
    )
    profile = load_json_object(profile_raw, label="frozen native profile")["validation"]["limitedNativeMatrix"]
    _validate_registered_profile(profile)
    return QualificationContext(
        manifest_digest=canonical_digest(actual),
        lock_sha256=hashlib.sha256(lock_raw).hexdigest(),
        profile_sha256=profile_sha256,
        admission_path=profile["evidenceContract"]["admissionPath"],
        route_id=ROUTE,
        claim=profile["claim"],
        rows=tuple(profile["rows"]),
        producer_paths=tuple(profile["evidenceContract"]["producerSources"]),
    )
