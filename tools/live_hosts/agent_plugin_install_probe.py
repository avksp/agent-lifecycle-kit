"""Run an explicit, bounded Agent Plugins client qualification probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_lifecycle.contracts import read_json_object, write_json_create
from agent_lifecycle.host_protocol.agent_plugin_qualification import run_agent_plugin_qualification_probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a locally installed Agent Plugins projection.")
    parser.add_argument("--adapter", required=True, choices=["codex", "claude", "cursor"])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--host-bin")
    parser.add_argument("--out")
    args = parser.parse_args()
    profile = read_json_object(Path(args.profile), label="Agent Plugins qualification profile")
    if profile.get("adapterId") != args.adapter:
        raise SystemExit("profile adapterId does not match --adapter")
    receipt = run_agent_plugin_qualification_probe(
        package_root=Path(args.package),
        project_root=Path(args.project_root),
        profile=profile,
        host_bin=args.host_bin,
    )
    if args.out:
        write_json_create(Path(args.out), receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "QUALIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
