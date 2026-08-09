from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_lifecycle.adapter_sessions.launcher import launch_from_local_profile  # noqa: E402
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile  # noqa: E402
from agent_lifecycle.contracts import canonical_digest  # noqa: E402

ADAPTER_ID = "codex"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight"], required=True)
    parser.add_argument("--approval-file", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    report = run_preflight(Path(args.approval_file))
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


if __name__ == "__main__":
    raise SystemExit(main())
