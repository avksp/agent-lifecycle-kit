from __future__ import annotations

import argparse
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
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile  # noqa: E402
from agent_lifecycle.contracts import canonical_digest  # noqa: E402

ADAPTER_ID = "codex"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight", "planning-preflight"], required=True)
    parser.add_argument("--approval-file", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    report = (
        run_preflight(Path(args.approval_file))
        if args.mode == "preflight"
        else run_planning_preflight(Path(args.approval_file))
    )
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


def run_preflight(approval_path: Path) -> dict[str, Any]:
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    blockers = _approval_blockers(approval)
    receipt = None
    if not blockers:
        with tempfile.TemporaryDirectory(prefix="alk-codex-preflight-") as tmp:
            root = Path(tmp)
            profile_path = root / ".alk/host-launch/codex.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(load_shipped_launch_profile(ADAPTER_ID, repository_root=ROOT)), encoding="utf-8")
            receipt = launch_from_local_profile(profile_path=profile_path, operation="preflight", project_root=root, process_env=dict(os.environ))
            blockers.extend(receipt.get("blockers", []))
    body = {
        "schemaVersion": "agent-qualified-host-launch-preflight.v1",
        "status": "PASS" if receipt and receipt.get("status") == "PASS" and not blockers else "FAIL",
        "adapterId": ADAPTER_ID,
        "approvalDigest": canonical_digest(approval),
        "processCalls": receipt.get("processCalls", 0) if receipt else 0,
        "modelCallsStarted": False,
        "receipt": receipt,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def run_planning_preflight(approval_path: Path) -> dict[str, Any]:
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    blockers = _planning_approval_blockers(approval)
    version_receipt = None
    planning_evidence = None
    if not blockers:
        with tempfile.TemporaryDirectory(prefix="alk-codex-planning-") as tmp:
            root = Path(tmp)
            _init_disposable_repository(root)
            profile_path = root / ".alk/host-launch/codex.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(
                json.dumps(load_shipped_launch_profile(ADAPTER_ID, repository_root=ROOT)),
                encoding="utf-8",
            )
            version_receipt = launch_from_local_profile(
                profile_path=profile_path,
                operation="preflight",
                project_root=root,
                process_env=dict(os.environ),
            )
            blockers.extend(version_receipt.get("blockers", []))
            if not blockers:
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    planning_evidence = run_planning_qualification_candidate(
                        profile_path=profile_path,
                        project_root=root,
                        approval_digest=canonical_digest(approval),
                        process_env=dict(os.environ),
                    )
                finally:
                    os.chdir(previous)
                blockers.extend(planning_evidence.get("blockers", []))
    body = {
        "schemaVersion": "agent-qualified-planning-launch-preflight.v1",
        "status": "PASS" if planning_evidence and planning_evidence.get("status") == "PASS" and not blockers else "FAIL",
        "adapterId": ADAPTER_ID,
        "approvalDigest": canonical_digest(approval),
        "processCalls": (version_receipt.get("processCalls", 0) if version_receipt else 0)
        + (planning_evidence.get("processCalls", 0) if planning_evidence else 0),
        "modelCallsStarted": bool(planning_evidence and planning_evidence.get("modelCallsStarted")),
        "versionReceipt": version_receipt,
        "planningEvidence": planning_evidence,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def _approval_blockers(approval: dict[str, Any]) -> list[dict[str, Any]]:
    valid = (
        approval.get("schemaVersion") == "agent-host-launch-preflight-approval.v1"
        and approval.get("approved") is True
        and approval.get("adapterId") == ADAPTER_ID
        and approval.get("maxProcesses") == 1
        and isinstance(approval.get("maxWallSeconds"), (int, float))
        and 0 < approval["maxWallSeconds"] <= 30
        and approval.get("modelTokenBudget") == 0
    )
    return [] if valid else [{"code": "host-launch-preflight-approval-invalid"}]


def _planning_approval_blockers(approval: dict[str, Any]) -> list[dict[str, Any]]:
    valid = (
        approval.get("schemaVersion") == "agent-planning-launch-qualification-approval.v1"
        and approval.get("approved") is True
        and approval.get("adapterId") == ADAPTER_ID
        and approval.get("maxProcesses") == 2
        and isinstance(approval.get("maxWallSeconds"), (int, float))
        and 0 < approval["maxWallSeconds"] <= 330
        and isinstance(approval.get("modelTokenBudget"), int)
        and 0 < approval["modelTokenBudget"] <= 20000
    )
    return [] if valid else [{"code": "planning-launch-preflight-approval-invalid"}]


def _init_disposable_repository(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "alk@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "ALK qualification"], cwd=root, check=True)
    (root / "README.md").write_text("# Disposable planning fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    raise SystemExit(main())
