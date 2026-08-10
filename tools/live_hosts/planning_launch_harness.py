"""Shared bounded live harness for exact-version planning launch profiles."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_lifecycle.adapter_sessions.launcher import (  # noqa: E402
    launch_from_local_profile,
    run_planning_qualification_candidate,
)
from agent_lifecycle.adapter_sessions.qualification import (  # noqa: E402
    load_shipped_launch_profile,
    planning_support_status,
)
from agent_lifecycle.contracts import canonical_digest  # noqa: E402


def main(adapter_id: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight", "planning-preflight"], required=True)
    parser.add_argument("--approval-file", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    approval_path = Path(args.approval_file)
    report = (
        run_version_preflight(adapter_id, approval_path)
        if args.mode == "preflight"
        else run_planning_preflight(adapter_id, approval_path)
    )
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


def run_version_preflight(adapter_id: str, approval_path: Path) -> dict[str, Any]:
    approval, blockers = _read_approval(approval_path)
    blockers.extend(_approval_blockers(approval, adapter_id, planning=False))
    receipt = None
    profile = load_shipped_launch_profile(adapter_id, repository_root=ROOT)
    if not blockers:
        profile = _with_timeout(profile, float(approval["maxWallSeconds"]))
        with tempfile.TemporaryDirectory(prefix=f"alk-{adapter_id}-preflight-") as tmp:
            root = Path(tmp).resolve()
            profile_path = _write_local_profile(root, adapter_id, profile)
            receipt = launch_from_local_profile(
                profile_path=profile_path,
                operation="preflight",
                project_root=root,
                process_env=dict(os.environ),
            )
            blockers.extend(receipt.get("blockers", []))
    return _report(
        schema_version="agent-qualified-host-launch-preflight.v1",
        adapter_id=adapter_id,
        approval=approval,
        profile=profile,
        version_receipt=receipt,
        planning_evidence=None,
        blockers=blockers,
    )


def run_planning_preflight(adapter_id: str, approval_path: Path) -> dict[str, Any]:
    approval, blockers = _read_approval(approval_path)
    blockers.extend(_approval_blockers(approval, adapter_id, planning=True))
    profile = load_shipped_launch_profile(adapter_id, repository_root=ROOT)
    planning = profile.get("planningOnly") if isinstance(profile.get("planningOnly"), dict) else {}
    if planning.get("status") != "CANDIDATE":
        blockers.append(
            {
                "code": "planning-qualification-candidate-unavailable",
                "reason": planning.get("reason", "adapter has no bounded planning candidate"),
            }
        )
    version_receipt = None
    planning_evidence = None
    if not blockers:
        with tempfile.TemporaryDirectory(prefix=f"alk-{adapter_id}-planning-") as tmp:
            root = Path(tmp).resolve()
            _init_disposable_repository(root)
            profile_path = _write_local_profile(root, adapter_id, profile)
            version_receipt = launch_from_local_profile(
                profile_path=profile_path,
                operation="preflight",
                project_root=root,
                process_env=dict(os.environ),
            )
            blockers.extend(version_receipt.get("blockers", []))
            if not blockers:
                probe_seconds = min(float(profile["timeoutSeconds"]), 10.0)
                planning_evidence = run_planning_qualification_candidate(
                    profile_path=profile_path,
                    project_root=root,
                    approval_digest=canonical_digest(approval),
                    max_wall_seconds=float(approval["maxWallSeconds"]) - probe_seconds,
                    model_token_budget=int(approval["modelTokenBudget"]),
                    process_env=dict(os.environ),
                )
                blockers.extend(planning_evidence.get("blockers", []))
    return _report(
        schema_version="agent-qualified-planning-launch-preflight.v1",
        adapter_id=adapter_id,
        approval=approval,
        profile=profile,
        version_receipt=version_receipt,
        planning_evidence=planning_evidence,
        blockers=blockers,
    )


def _report(
    *,
    schema_version: str,
    adapter_id: str,
    approval: dict[str, Any],
    profile: dict[str, Any],
    version_receipt: dict[str, Any] | None,
    planning_evidence: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    process_calls = (version_receipt.get("processCalls", 0) if version_receipt else 0) + (
        planning_evidence.get("processCalls", 0) if planning_evidence else 0
    )
    is_planning = schema_version == "agent-qualified-planning-launch-preflight.v1"
    passed = bool(
        not blockers
        and version_receipt
        and version_receipt.get("status") == "PASS"
        and (not is_planning or (planning_evidence and planning_evidence.get("status") == "PASS"))
    )
    planning = profile.get("planningOnly") if isinstance(profile.get("planningOnly"), dict) else {}
    body = {
        "schemaVersion": schema_version,
        "status": "PASS" if passed else "FAIL",
        "adapterId": adapter_id,
        "expectedHostVersion": (profile.get("qualification") or {}).get("expectedVersion"),
        "profileStatus": planning.get("status"),
        "planningSupportStatus": planning_support_status(profile),
        "approvalDigest": canonical_digest(approval),
        "processCalls": process_calls,
        "modelCallsStarted": bool(planning_evidence and planning_evidence.get("modelCallsStarted")),
        "versionReceipt": version_receipt,
        "planningEvidence": planning_evidence,
        "blockers": blockers,
        "publicSupportClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def _read_approval(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, [{"code": "planning-launch-approval-unreadable"}]
    if not isinstance(value, dict):
        return {}, [{"code": "planning-launch-approval-not-object"}]
    return value, []


def _approval_blockers(approval: dict[str, Any], adapter_id: str, *, planning: bool) -> list[dict[str, Any]]:
    if planning:
        valid = (
            approval.get("schemaVersion") == "agent-planning-launch-qualification-approval.v1"
            and approval.get("approved") is True
            and approval.get("adapterId") == adapter_id
            and approval.get("maxProcesses") == 2
            and isinstance(approval.get("maxWallSeconds"), (int, float))
            and 10 < approval["maxWallSeconds"] <= 330
            and isinstance(approval.get("modelTokenBudget"), int)
            and 0 < approval["modelTokenBudget"] <= 20000
        )
    else:
        valid = (
            approval.get("schemaVersion") == "agent-host-launch-preflight-approval.v1"
            and approval.get("approved") is True
            and approval.get("adapterId") == adapter_id
            and approval.get("maxProcesses") == 1
            and isinstance(approval.get("maxWallSeconds"), (int, float))
            and 0 < approval["maxWallSeconds"] <= 30
            and approval.get("modelTokenBudget") == 0
        )
    code = "planning-launch-preflight-approval-invalid" if planning else "host-launch-preflight-approval-invalid"
    return [] if valid else [{"code": code}]


def _write_local_profile(root: Path, adapter_id: str, profile: dict[str, Any]) -> Path:
    path = root / ".alk" / "host-launch" / f"{adapter_id}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def _with_timeout(profile: dict[str, Any], max_wall_seconds: float) -> dict[str, Any]:
    bounded = copy.deepcopy(profile)
    bounded["timeoutSeconds"] = min(float(profile["timeoutSeconds"]), max_wall_seconds)
    return bounded


def _init_disposable_repository(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "alk@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "ALK qualification"], cwd=root, check=True)
    (root / "README.md").write_text("# Disposable planning fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
