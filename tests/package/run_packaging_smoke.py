from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    dist_dir = Path(args.dist_dir)
    evidence_path = Path(args.evidence)
    blockers: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)

    _run_command([sys.executable, "-m", "build", "--outdir", str(dist_dir)], commands, blockers)
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        blockers.append({"code": "wheel-not-built", "message": "build did not produce a wheel"})
    else:
        with tempfile.TemporaryDirectory() as tmp:
            venv_dir = Path(tmp) / "venv"
            venv.EnvBuilder(with_pip=True).create(venv_dir)
            python = _venv_python(venv_dir)
            _run_command([str(python), "-m", "pip", "install", "--force-reinstall", str(wheels[0])], commands, blockers)
            _run_command([str(_venv_script(venv_dir, "agent-lifecycle")), "version"], commands, blockers)
            _run_command([str(_venv_script(venv_dir, "agent-lifecycle-neutrality")), "--help"], commands, blockers)
            marker = _probe_type_marker(python)
            commands.append({"argv": _portable_argv([str(python), "-c", "py.typed probe"]), "returncode": 0 if marker else 1})
            if not marker:
                blockers.append({"code": "py-typed-missing", "message": "installed wheel does not include agent_lifecycle/py.typed"})

    status = "PASS" if not blockers else "FAIL"
    evidence = {
        "schemaVersion": "agent-packaging-smoke-evidence.v1",
        "status": status,
        "distDir": _portable_path(dist_dir),
        "commands": commands,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def _run_command(argv: list[str], commands: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    result = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
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


def _portable_argv(argv: list[str]) -> list[str]:
    return [_portable_path(item, executable=index == 0) for index, item in enumerate(argv)]


def _portable_path(value: str | Path, *, executable: bool = False) -> str:
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        name = path.name
        if executable and name.startswith("python"):
            return "python"
        return name or "external-path"


def _stream_identity(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8")
    return {"bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}


def _probe_type_marker(python: Path) -> bool:
    code = (
        "import importlib.resources as r; "
        "raise SystemExit(0 if (r.files('agent_lifecycle') / 'py.typed').is_file() else 1)"
    )
    result = subprocess.run([str(python), "-c", code], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
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
