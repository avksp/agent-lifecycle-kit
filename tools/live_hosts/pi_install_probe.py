from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.contracts import canonical_digest, sha256_hex  # noqa: E402
from tools.live_hosts.json_cli_harness import first_line, write_json  # noqa: E402


REPORT_SCHEMA = "agent-pi-install-probe-report.v1"
DEFAULT_DESCRIPTOR = Path("adapters/pi/adapter.descriptor.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pi-bin", default="pi")
    parser.add_argument("--descriptor", default=DEFAULT_DESCRIPTOR.as_posix())
    parser.add_argument("--approved-source", required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    report = run_probe(
        pi_bin=args.pi_bin,
        descriptor=Path(args.descriptor),
        approved_source=args.approved_source,
        expected_version=args.expected_version,
    )
    write_json(Path(args.report), report)
    return 0 if report["status"] == "PASS" else 1


def run_probe(*, pi_bin: str, descriptor: Path, approved_source: str, expected_version: str | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    version = _run([pi_bin, "--version"], checks, "pi-version")
    help_result = _run([pi_bin, "--help"], checks, "pi-help")
    install_plan = _run(
        [
            sys.executable,
            "-m",
            "agent_lifecycle",
            "adapter",
            "install-plan",
            "--descriptor",
            descriptor.as_posix(),
        ],
        checks,
        "pi-adapter-install-plan",
        env_with_pythonpath=True,
    )
    version_line = first_line(version["stdout"])
    if expected_version and version_line != expected_version:
        blockers.append({"code": "pi-version-mismatch", "message": "installed Pi version does not match the expected version"})
    if not approved_source.strip():
        blockers.append({"code": "pi-install-source-missing", "message": "--approved-source must name the operator-approved source"})
    install_plan_digest = sha256_hex(install_plan["stdout"].encode("utf-8")) if install_plan["returncode"] == 0 else None
    commands_ok = all(item["returncode"] == 0 for item in (version, help_result, install_plan))
    return {
        "schemaVersion": REPORT_SCHEMA,
        "status": "PASS" if commands_ok and not blockers else "FAIL",
        "host": "pi",
        "approvedSourceDigest": canonical_digest({"approvedSource": approved_source}),
        "piVersion": version_line,
        "expectedVersion": expected_version,
        "installPlanStdoutSha256": install_plan_digest,
        "checks": checks,
        "blockers": blockers,
        "writesStarted": False,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }


def _run(command: list[str], checks: list[dict[str, Any]], name: str, *, env_with_pythonpath: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    env = None
    if env_with_pythonpath:
        import os

        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    elapsed = round(time.monotonic() - started, 3)
    checks.append(
        {
            "name": name,
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "returncode": result.returncode,
            "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")),
            "stderrSha256": sha256_hex(result.stderr.encode("utf-8")),
            "wallSeconds": elapsed,
        }
    )
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


if __name__ == "__main__":
    raise SystemExit(main())
