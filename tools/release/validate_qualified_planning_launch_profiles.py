from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile  # noqa: E402
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile  # noqa: E402
from agent_lifecycle.contracts import canonical_digest  # noqa: E402

TARGETS = ("codex", "claude", "opencode")


def validate_profiles(
    adapter_root: Path,
    *,
    repository_root: Path | None = None,
    targets: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = (repository_root or adapter_root.parent).resolve()
    selected_targets = targets or TARGETS
    blockers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for adapter_id in selected_targets:
        try:
            profile = load_shipped_launch_profile(adapter_id, repository_root=root)
            descriptor = json.loads((adapter_root / adapter_id / "adapter.descriptor.json").read_text(encoding="utf-8"))
            capabilities = json.loads((adapter_root / adapter_id / "capabilities.manifest.json").read_text(encoding="utf-8"))
        except Exception as exc:
            blockers.append({"code": "planning-profile-load-failed", "adapterId": adapter_id, "errorType": type(exc).__name__})
            continue
        validation = validate_local_launch_profile(profile)
        planning = profile.get("planningOnly") if isinstance(profile.get("planningOnly"), dict) else {}
        support = planning.get("planningSupportStatus")
        status = planning.get("status")
        adapter_blockers: list[dict[str, Any]] = list(validation.get("blockers", []))
        descriptor_planning = descriptor.get("qualifiedLaunch", {})
        capability_planning = capabilities.get("planningLaunch", {})
        if descriptor_planning.get("planningSupportStatus") != support:
            adapter_blockers.append({"code": "planning-profile-descriptor-drift"})
        if capability_planning.get("planningSupportStatus") != support:
            adapter_blockers.append({"code": "planning-profile-capability-drift"})
        if capability_planning.get("profileStatus") != status:
            adapter_blockers.append({"code": "planning-profile-status-drift"})
        evidence = planning.get("qualificationEvidence")
        if support == "PLANNING_ONLY_QUALIFIED" and (not isinstance(evidence, list) or not evidence):
            adapter_blockers.append({"code": "planning-profile-live-evidence-missing"})
        if status == "UNSUPPORTED" and support != "PLANNING_ONLY_UNSUPPORTED":
            adapter_blockers.append({"code": "planning-profile-unsupported-claim"})
        if adapter_blockers:
            blockers.extend({**item, "adapterId": adapter_id} for item in adapter_blockers)
        rows.append(
            {
                "adapterId": adapter_id,
                "profileStatus": status,
                "planningSupportStatus": support,
                "qualificationEvidenceCount": len(evidence) if isinstance(evidence, list) else 0,
                "status": "PASS" if not adapter_blockers else "FAIL",
            }
        )
    body = {
        "schemaVersion": "agent-qualified-planning-launch-profile-validation.v1",
        "status": "PASS" if not blockers and len(rows) == len(selected_targets) else "FAIL",
        "profiles": rows,
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    report = validate_profiles(Path(args.adapter_root))
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
