from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json

FORBIDDEN_SNIPPETS = (
    "shell=True",
    "os.system(",
    "subprocess.Popen(",
    "pty.spawn(",
    "pexpect.",
    ".write_text(",
    ".write_bytes(",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    blockers: list[dict[str, Any]] = []
    scanned: list[dict[str, Any]] = []
    for raw in args.paths:
        path = Path(raw)
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for file_path in files:
            text = file_path.read_text(encoding="utf-8")
            scanned.append(file_identity(file_path))
            for snippet in FORBIDDEN_SNIPPETS:
                if snippet in text and not _allowed_write(file_path, snippet):
                    blockers.append({"code": "adapter-launcher-forbidden-snippet", "path": file_path.as_posix(), "snippet": snippet})
            blockers.extend(_boundary_blockers(file_path, text))
    body = {
        "schemaVersion": "agent-adapter-launcher-security-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "scannedFiles": scanned,
        "blockers": blockers,
        "requiredInvariants": {
            "argvArrays": True,
            "shellFalse": True,
            "envAllowlist": True,
            "redactedReceipts": True,
            "nativeConfigWrites": False,
            "secretStorage": False,
            "genericDescriptorLaunch": False,
            "exactEnvironmentNames": True,
        },
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _allowed_write(path: Path, snippet: str) -> bool:
    if path.as_posix().endswith("session_store.py") and snippet in {".write_text(", ".write_bytes("}:
        return True
    return False


def _boundary_blockers(path: Path, text: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if path.name == "launcher.py":
        if "adapter-generic-launch-disabled" not in text:
            blockers.append({"code": "adapter-generic-launch-blocker-missing", "path": path.as_posix()})
        if "run_process(" in text or "subprocess.run(" in text:
            blockers.append({"code": "adapter-generic-launch-process-route", "path": path.as_posix()})
    if path.name == "env.py":
        if "import fnmatch" in text or "fnmatch." in text:
            blockers.append({"code": "adapter-env-wildcard-route", "path": path.as_posix()})
        if "adapter-env-wildcard-disallowed" not in text:
            blockers.append({"code": "adapter-env-wildcard-blocker-missing", "path": path.as_posix()})
    return blockers


if __name__ == "__main__":
    raise SystemExit(main())
