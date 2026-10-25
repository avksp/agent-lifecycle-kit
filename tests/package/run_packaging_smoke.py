from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    dist_dir = Path(args.dist_dir)
    evidence_path = Path(args.evidence)
    blockers: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    artifact_checks: list[dict[str, Any]] = []
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)

    _run_command(
        [
            args.python,
            "-m",
            "build",
            "--outdir",
            str(dist_dir.resolve()),
            str(ROOT),
        ],
        commands,
        blockers,
        cwd=ROOT.parent,
    )
    wheels = sorted(dist_dir.glob("*.whl"))
    source_distributions = sorted([*dist_dir.glob("*.tar.gz"), *dist_dir.glob("*.zip")])
    if not wheels:
        blockers.append({"code": "wheel-not-built", "message": "build did not produce a wheel"})
    if not source_distributions:
        blockers.append({"code": "sdist-not-built", "message": "build did not produce a source distribution"})
    with tempfile.TemporaryDirectory() as tmp:
        artifact_root = Path(tmp)
        expected = _runtime_inventory(ROOT)
        for kind, artifacts in (("wheel", wheels), ("sdist", source_distributions)):
            if len(artifacts) > 1:
                blockers.append({"code": "packaging-artifact-ambiguous", "artifactKind": kind})
            if artifacts:
                inventory = _check_runtime_members(kind, artifacts[0], expected)
                if inventory["status"] != "PASS":
                    blockers.append({"code": "packaging-runtime-members-differ", "artifactKind": kind, **inventory})
                    artifact_checks.append({"kind": kind, "status": "FAIL", "runtimeInventory": inventory})
                    continue
                result = _check_artifact(
                    kind, artifacts[0], args.python, artifact_root / f"{kind}-venv", commands, blockers
                )
                result["runtimeInventory"] = inventory
                artifact_checks.append(result)

    status = "PASS" if not blockers else "FAIL"
    evidence = {
        "schemaVersion": "agent-packaging-smoke-evidence.v1",
        "status": status,
        "distDir": _portable_path(dist_dir),
        "python": _portable_path(args.python, executable=True),
        "artifactChecks": artifact_checks,
        "commands": commands,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def _runtime_inventory(root: Path) -> dict[str, str]:
    """Read the actual export or checkout source, independent of Git and caches."""
    package = root / "src/agent_lifecycle"
    inventory = {}
    for path in sorted(package.rglob("*")):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError("Runtime source symlink refused")
        if path.is_file():
            name = path.relative_to(root / "src").as_posix()
            inventory[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not inventory:
        raise ValueError("Runtime source inventory required")
    return inventory


def _check_runtime_members(kind: str, artifact: Path, expected: dict[str, str]) -> dict[str, Any]:
    """Reject stale, missing, changed or duplicate package members before install."""
    actual: dict[str, str] = {}

    def add(name: str, raw: bytes) -> None:
        if name in actual:
            raise ValueError("Duplicate runtime package member")
        actual[name] = hashlib.sha256(raw).hexdigest()

    try:
        if kind == "wheel" or (kind == "sdist" and zipfile.is_zipfile(artifact)):
            with zipfile.ZipFile(artifact) as archive:
                for member in archive.infolist():
                    name = member.filename
                    if kind == "sdist":
                        parts = name.split("/")
                        name = "/".join(parts[2:]) if parts[1:3] == ["src", "agent_lifecycle"] else ""
                    if name.startswith("agent_lifecycle/") and not member.is_dir():
                        if stat.S_ISLNK(member.external_attr >> 16):
                            raise ValueError("Runtime archive symlink refused")
                        add(name, archive.read(member))
        elif kind == "sdist":
            with tarfile.open(artifact, "r:*") as archive:
                for member in archive.getmembers():
                    parts = member.name.split("/")
                    if parts[1:3] == ["src", "agent_lifecycle"] and not member.isdir():
                        if not member.isfile():
                            raise ValueError("Runtime archive link refused")
                        stream = archive.extractfile(member)
                        if stream is None:
                            raise ValueError("Runtime archive member unreadable")
                        with stream:
                            add("/".join(parts[2:]), stream.read())
        else:
            raise ValueError("Unsupported runtime artifact kind")
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return {"status": "FAIL", "errorType": type(exc).__name__}
    missing = sorted(expected.keys() - actual.keys())
    unexpected = sorted(actual.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & actual.keys() if expected[name] != actual[name])
    identity = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    return {
        "status": "FAIL" if missing or unexpected or changed else "PASS",
        "sourceInventoryDigest": identity,
        "sourceMemberCount": len(expected),
        "artifactMemberCount": len(actual),
        "missing": missing,
        "unexpected": unexpected,
        "changed": changed,
    }


def _check_artifact(
    kind: str,
    artifact: Path,
    python_executable: str,
    venv_dir: Path,
    commands: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    command_start = len(commands)
    blocker_start = len(blockers)
    created = _run_command([python_executable, "-m", "venv", str(venv_dir)], commands, blockers) == 0
    if created:
        python = _venv_python(venv_dir)
        _run_command([str(python), "-m", "pip", "install", "--force-reinstall", str(artifact)], commands, blockers)
        outside = venv_dir.parent / f"{kind}-outside"
        outside.mkdir(parents=True, exist_ok=True)
        lifecycle = _venv_script(venv_dir, "agent-lifecycle")
        _run_command([str(lifecycle), "version"], commands, blockers, cwd=outside)
        _run_command(
            [str(_venv_script(venv_dir, "agent-lifecycle-neutrality")), "--help"], commands, blockers, cwd=outside
        )
        request = outside / "model-route-request.json"
        request.write_text(json.dumps(_model_route_request()), encoding="utf-8")
        _run_command([str(lifecycle), "model", "route", "--request", str(request)], commands, blockers, cwd=outside)
        _run_command([str(lifecycle), "project", "preset", "list"], commands, blockers, cwd=outside)
        marker = _probe_type_marker(python)
        commands.append(
            {"argv": _portable_argv([str(python), "-c", "py.typed probe"]), "returncode": 0 if marker else 1}
        )
        if not marker:
            blockers.append(
                {"code": "py-typed-missing", "artifactKind": kind, "message": "installed package lacks py.typed"}
            )
    return {
        "kind": kind,
        "status": "PASS" if len(blockers) == blocker_start else "FAIL",
        "artifactIdentity": _file_identity(artifact),
        "commandRange": {"start": command_start, "end": len(commands)},
    }


def _run_command(
    argv: list[str],
    commands: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    *,
    cwd: Path = ROOT,
) -> int:
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    portable_argv = _portable_argv(argv)
    commands.append({"argv": portable_argv, "returncode": result.returncode})
    if result.returncode != 0:
        blockers.append(
            {
                "code": "packaging-command-failed",
                "argv": portable_argv,
                "stdoutIdentity": _stream_identity(result.stdout),
                "stderrIdentity": _stream_identity(result.stderr),
            }
        )
    return result.returncode


def _portable_argv(argv: list[str]) -> list[str]:
    return [_portable_path(item, executable=index == 0) for index, item in enumerate(argv)]


def _portable_path(value: str | Path, *, executable: bool = False) -> str:
    raw_value = str(value)
    path = Path(raw_value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            name = path.name
    elif PurePosixPath(raw_value).is_absolute():
        name = PurePosixPath(raw_value).name
    elif PureWindowsPath(raw_value).is_absolute():
        name = PureWindowsPath(raw_value).name
    else:
        return path.as_posix()
    if executable and name.lower().startswith("python"):
        return "python"
    return name or "external-path"


def _stream_identity(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8")
    return {"bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}


def _file_identity(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"name": path.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _model_route_request() -> dict[str, Any]:
    return {
        "schemaVersion": "agent-lifecycle-model-route-request.v1",
        "operationId": "packaging-smoke",
        "phase": "triage",
        "sddTier": "S0",
        "riskFlags": {},
        "capabilityRequirements": ["text", "json"],
        "targetContextWindow": "8k",
        "routingPolicy": "balanced",
        "budgetClass": "normal",
        "userPolicy": {"localModelsAllowed": False, "cloudModelsAllowed": True},
    }


def _probe_type_marker(python: Path) -> bool:
    code = (
        "import importlib.resources as r; "
        "raise SystemExit(0 if (r.files('agent_lifecycle') / 'py.typed').is_file() else 1)"
    )
    result = subprocess.run([str(python), "-c", code], text=True, capture_output=True, check=False)
    return result.returncode == 0


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts/python.exe"
    return venv_dir / "bin/python"


def _venv_script(venv_dir: Path, name: str) -> Path:
    if sys.platform == "win32":
        return venv_dir / f"{name}.exe"
    return venv_dir / "bin" / name


if __name__ == "__main__":
    raise SystemExit(main())
