from __future__ import annotations

import argparse
from pathlib import Path

from release_common import digest_value, file_identity, load_json, write_json


REQUIRED_RELEASE_EVIDENCE = (
    "release-assembly.json",
    "release-verification.json",
    "support-matrix-contract.json",
    "deferred-promotion-contract.json",
    "release-neutrality-report.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--release-evidence-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    manifest = load_json(Path(args.manifest))
    state = load_json(Path(args.state))
    evidence_dir = Path(args.release_evidence_dir)
    missing = [name for name in REQUIRED_RELEASE_EVIDENCE if not (evidence_dir / name).is_file()]
    task_statuses = {task.get("id"): task.get("status") for task in state.get("tasks", [])}
    required_tasks = [f"WS-{index:02d}" for index in range(1, 15)]
    not_accepted = [task_id for task_id in required_tasks if task_statuses.get(task_id) != "ACCEPTED"]
    status = "PASS" if not missing and not not_accepted else "FAIL"
    output = {
        "schemaVersion": "agent-final-candidate-audit.v1",
        "semanticStatus": "READY_FOR_FINALIZATION" if status == "PASS" else "CHANGES_REQUIRED",
        "status": status,
        "planRevision": manifest.get("planRevision"),
        "planDigest": digest_value(manifest),
        "stateRevision": state.get("stateRevision"),
        "missingReleaseEvidence": missing,
        "notAcceptedTasks": not_accepted,
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    if status == "PASS":
        output["releaseEvidence"] = [file_identity(evidence_dir / name) for name in REQUIRED_RELEASE_EVIDENCE]
    write_json(Path(args.output), output)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
