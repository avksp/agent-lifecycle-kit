from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.compiler import compile_task_packets  # noqa: E402
from agent_lifecycle.context import check_context  # noqa: E402
from agent_lifecycle.contracts import LifecycleError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--target-windows", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    windows = [item.strip() for item in args.target_windows.split(",") if item.strip()]
    out_dir = Path(args.out_dir)
    compiled = compile_task_packets(Path(args.manifest), out_dir=out_dir, write=True)
    checks = []
    for packet in sorted(compiled["index"]["packets"], key=lambda item: item["taskId"]):
        packet_path = Path(packet["path"])
        for window in windows:
            checks.append(_check_packet(Path(args.profile), packet_path, Path(args.summary), packet["taskId"], window))
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    evidence = {
        "schemaVersion": "agent-task-packet-context-fit.v1",
        "status": status,
        "manifest": args.manifest,
        "packetIndex": compiled["index"],
        "targetWindows": windows,
        "checks": checks,
        "productionPromotionClaimed": False,
    }
    path = Path(args.evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def _check_packet(profile: Path, packet: Path, summary: Path, task_id: str, window: str) -> dict[str, Any]:
    try:
        payload = check_context(profile, packet, summary, latest_user="Implement the active task packet.", window=window)
    except LifecycleError as exc:
        return {
            "taskId": task_id,
            "window": window,
            "status": "FAIL",
            "error": exc.to_json(),
        }
    return {
        "taskId": task_id,
        "window": window,
        "status": payload["status"],
        "receipt": payload["receipt"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
