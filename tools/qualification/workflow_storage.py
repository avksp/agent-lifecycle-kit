"""Contained, source-bound incident migration rehearsal; never live recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

FIELDS = {
    "schemaVersion",
    "sourceRoot",
    "backupRoot",
    "sourceHead",
    "runtimeSourceRevision",
    "state",
    "eventLog",
    "relocations",
    "files",
}
INCIDENT_HEAD = "4138419ffbf3df1a0c305a30ae667d4c45fbd82a"
INCIDENT_SHA = "2b76dd7f75d5394e2816edf96deef7cd112631d52ebab6622bc3b07daba2fa0a"
SHA = re.compile(r"[0-9a-f]{64}\Z")
_PARTIAL: Path | None = None


def identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("nonportable relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(
            part in {".", ".."}
            or part.casefold() == ".git"
            or part.endswith((".", " "))
            or part.split(".")[0].casefold()
            in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
            for part in path.parts
        )
    ):
        raise ValueError("aliased, escaping or Git metadata path")
    return value


def contained(root: Path, value: str, *, allow_missing: bool = False) -> Path:
    path = root / relative(value)
    for parent in (root, *path.relative_to(root).parents):
        candidate = parent if parent == root else root / parent
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("symlink/reparse ancestor")
    if path.is_symlink():
        raise ValueError("symlink leaf")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("path escapes root")
    if not allow_missing and not path.is_file():
        raise ValueError(f"missing input: {value}")
    if path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("reparse leaf")
    return path


def check_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("whole rehearsal deadline expired")


def validate_input(value: Any, replica: Path, deadline: float) -> tuple[Path, Path]:
    if not isinstance(value, dict) or set(value) != FIELDS or value["schemaVersion"] != "rmk-replay-input.v1":
        raise ValueError("invalid exact rmk-replay-input.v1 fields")
    roots = []
    for key in ("sourceRoot", "backupRoot"):
        raw = value[key]
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError("input roots must be absolute")
        root = Path(raw)
        if root != root.resolve() or not root.is_dir():
            raise ValueError("root alias or absent root")
        roots.append(root)
        if replica == root or replica.is_relative_to(root) or root.is_relative_to(replica):
            raise ValueError("replica overlaps protected root")
    if replica.exists() or replica.is_symlink() or replica != replica.resolve():
        raise ValueError("replica must be fresh and canonical")
    source, backup = roots
    if value["sourceHead"] != INCIDENT_HEAD:
        raise ValueError("wrong historical source head")
    files = value["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("complete file map is required")
    seen: set[str] = set()
    archived: set[str] = set()
    ordered = []
    for item in files:
        check_time(deadline)
        if not isinstance(item, dict) or set(item) != {"originalPath", "archivedPath", "sha256", "bytes"}:
            raise ValueError("invalid file-map fields")
        original = relative(item["originalPath"])
        key = unicodedata.normalize("NFC", original).casefold()
        archive = relative(item["archivedPath"])
        archive_key = unicodedata.normalize("NFC", archive).casefold()
        if any(key == old or key.startswith(old + "/") or old.startswith(key + "/") for old in seen):
            raise ValueError("overlapping/aliased original paths")
        if archive_key in archived:
            raise ValueError("duplicate archived path")
        seen.add(key)
        archived.add(archive_key)
        ordered.append(original)
        if (
            not isinstance(item["sha256"], str)
            or not SHA.fullmatch(item["sha256"])
            or type(item["bytes"]) is not int
            or item["bytes"] < 0
            or identity(contained(backup, archive)) != {k: item[k] for k in ("sha256", "bytes")}
        ):
            raise ValueError("file-map raw identity mismatch")
    if ordered != sorted(ordered):
        raise ValueError("file map is not ordered")
    for key in ("state", "eventLog", "relocations"):
        entry = value[key]
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            raise ValueError("invalid input identity")
        matches = [item for item in files if item["originalPath"] == entry["path"]]
        if len(matches) != 1 or any(matches[0][field] != entry[field] for field in ("sha256", "bytes")):
            raise ValueError("input identity absent from complete map")
    if value["state"]["sha256"] != INCIDENT_SHA or value["state"]["bytes"] != 975748:
        raise ValueError("wrong revision64 incident state")
    validate_material_map(value, backup)
    return source, backup


def validate_material_map(value: dict[str, Any], backup: Path) -> None:
    inventory = json.loads(contained(backup, "inventory.json").read_bytes())
    if inventory["files"] != value["files"] or inventory["sourceHead"] != value["sourceHead"]:
        raise ValueError("incomplete historical material inventory")
    bundle = inventory["gitBundle"]
    if identity(contained(backup, bundle["path"])) != {key: bundle[key] for key in ("sha256", "bytes")}:
        raise ValueError("historical Git bundle identity mismatch")
    row = next(item for item in value["files"] if item["originalPath"] == value["relocations"]["path"])
    relocations = json.loads(contained(backup, row["archivedPath"]).read_bytes())
    indexed = {item["originalPath"]: item for item in value["files"]}
    for move in relocations["moves"]:
        original = relative(move["oldPath"])
        relative(move["newPath"])
        if original not in indexed or any(move[key] != indexed[original][key] for key in ("sha256", "bytes")):
            raise ValueError("missing or changed historical relocation")
    if relocations["headBefore"] != value["sourceHead"]:
        raise ValueError("relocation source differs")


def runtime_binding(input_path: Path, value: dict[str, Any], runtime: Path) -> dict[str, Any]:
    companion_path = input_path.with_suffix(".runtime-source.json")
    companion = json.loads(companion_path.read_bytes())
    files = {p.relative_to(runtime).as_posix(): identity(p)["sha256"] for p in sorted((runtime / "src").rglob("*.py"))}
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=runtime, text=True).strip()
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD", "--", "src"], cwd=runtime)
    if head != value["runtimeSourceRevision"] or head != companion["runtimeSourceRevision"]:
        raise ValueError("runtime base revision differs")
    if companion["runtimeSourceFiles"] != files or companion["input"]["sha256"] != identity(input_path)["sha256"]:
        raise ValueError("runtime overlay/input differs from source binding")
    if companion["trackedRuntimeDiffRawSha256"] != hashlib.sha256(diff).hexdigest():
        raise ValueError("runtime tracked dirty context differs")
    material = companion["materialInventory"]
    material_path = runtime / material["path"]
    if (
        material_path.resolve() != Path(value["backupRoot"]) / "inventory.json"
        or identity(material_path)["sha256"] != material["rawSha256"]
    ):
        raise ValueError("material inventory companion binding differs")
    return {
        "gitBase": head,
        "files": files,
        "trackedDiffSha256": hashlib.sha256(diff).hexdigest(),
        "uncommittedOverlay": True,
        "companion": identity(companion_path),
        "qualifier": identity(Path(__file__)),
    }


def run_child(
    argv: list[str], root: Path, deadline: float, observations: list[dict[str, Any]], protected=None, env=None
):
    check_time(deadline)
    before = protected() if protected else None
    record = {
        "argv": argv,
        "cwd": str(root),
        "startedAt": datetime.now(UTC).isoformat(),
        "protectedBefore": before,
        "separatelyCharged": False,
    }
    observations.append(record)
    emit_observation(record, "before-launch")
    process = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = process.communicate(timeout=max(0.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        record.update(timedOut=True, stdout=stdout, stderr=stderr)
        raise TimeoutError("child cancelled at whole rehearsal deadline") from None
    finally:
        record.update(
            endedAt=datetime.now(UTC).isoformat(),
            exitCode=process.returncode,
            protectedAfter=protected() if protected else None,
        )
        record.update(stdout=stdout, stderr=stderr)
        emit_observation(record, "child-ended")
    record.update(stdout=stdout, stderr=stderr)
    record["protectedStable"] = record["protectedBefore"] == record["protectedAfter"]
    return process.returncode, stdout + stderr


def emit_observation(record: dict[str, Any], stage: str) -> None:
    if _PARTIAL is not None:
        with _PARTIAL.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"stage": stage, **record}, sort_keys=True) + "\n")


def authority_containment(replica: Path, state_path: Path) -> dict[str, Any]:
    state = json.loads(state_path.read_bytes())
    package = (state_path.parent / state.get("packageRoot", ".")).resolve()
    if package != replica:
        raise ValueError("package root escapes independent replica")
    checked = [str(state_path), str(state_path.with_name(state_path.name + ".storage")), str(replica / ".alk")]

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key
                    in {
                        "path",
                        "manifestPath",
                        "eventLog",
                        "reviewPath",
                        "planArtifactRoot",
                        "artifactRoot",
                        "backupPath",
                    }
                    or key in {"result", "review", "implementationAudit", "implementationAuditReport"}
                ) and isinstance(item, str):
                    # Artifact templates are contained declarations, not open targets.
                    target = contained(replica, item, allow_missing=True)
                    checked.append(str(target))
                elif key == "artifactPaths" and isinstance(item, dict):
                    for declared in item.values():
                        checked.append(str(contained(replica, declared, allow_missing=True)))
                elif key != "packageRoot":
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(state)
    if "storage" in state:
        checked.append(str(contained(replica, state["storage"]["root"], allow_missing=True)))
    manifest_path = contained(replica, state["manifestPath"])
    manifest = json.loads(manifest_path.read_bytes())
    walk(manifest)
    lock_path = contained(replica, manifest["package"]["planArtifactRoot"] + "/plan.lock.json")
    walk(json.loads(lock_path.read_bytes()))
    checked.extend((str(manifest_path), str(lock_path)))
    git = replica / ".git"
    if (
        not git.is_dir()
        or git.is_symlink()
        or (git / "objects/info/alternates").exists()
        or (git / "commondir").exists()
        or (git / "worktrees").exists()
    ):
        raise ValueError("Git is not independent")
    for path in replica.rglob("*"):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("replica contains symlink/reparse")
    config = subprocess.check_output(
        ["git", "config", "--local", "--get", "core.hooksPath"], cwd=replica, text=True
    ).strip()
    if Path(config) != replica / ".git/disabled-hooks":
        raise ValueError("Git hook destination escapes disabled contained location")
    lock_key = unicodedata.normalize("NFC", state_path.resolve().as_posix()).casefold()
    lock = (
        Path.home().resolve()
        / ".agent-lifecycle-kit/workflow-locks"
        / (hashlib.sha256(lock_key.encode()).hexdigest() + ".lock")
    )
    return {
        "state": str(state_path),
        "packageRoot": str(package),
        "checkedPaths": sorted(set(checked)),
        "git": str(git),
        "soleProcessLockException": str(lock),
    }


def rehearse(args, report: dict[str, Any]) -> None:
    deadline = time.monotonic() + args.timeout_seconds
    input_path, replica = args.input.resolve(), args.replica_root.absolute()
    value = json.loads(input_path.read_bytes())
    source, backup = validate_input(value, replica, deadline)
    runtime = Path(__file__).resolve().parents[2]
    report.update(input=identity(input_path), runtime=runtime_binding(input_path, value, runtime), observations=[])
    observations = report["observations"]
    replica.mkdir(parents=True)
    env = isolated_environment(runtime)
    git_commands = (
        ["git", "init", "-q"],
        ["git", "config", "core.hooksPath", str(replica / ".git/disabled-hooks")],
        ["git", "fetch", "--no-tags", str(backup / "repository-before.bundle"), value["sourceHead"]],
        ["git", "reset", "--hard", "FETCH_HEAD"],
    )
    for argv in git_commands:
        code, output = run_child(argv, replica, deadline, observations, env=env)
        if code:
            raise ValueError(f"independent Git preparation refused: {output}")
    for item in value["files"]:
        check_time(deadline)
        target = contained(replica, item["originalPath"], allow_missing=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(contained(backup, item["archivedPath"]), target)
        if identity(target) != {k: item[k] for k in ("sha256", "bytes")}:
            raise ValueError("materialized identity differs")
    state_path = contained(replica, value["state"]["path"])
    events = contained(replica, value["eventLog"]["path"])
    old_events = events.read_bytes()
    before = json.loads(state_path.read_bytes())
    if (
        before["stateRevision"] != 64
        or before["phase"] != "BLOCKED"
        or before["schemaVersion"] != "agent-workflow-state.v4"
    ):
        raise ValueError("historical incident does not match")
    ledger = before["operationLedger"]
    lines = [json.loads(line) for line in old_events.splitlines()]
    if len(lines) != len(ledger) or len(lines) != 63:
        raise ValueError("historical event prefix/ledger count differs")
    report.update(
        materializedFiles=len(value["files"]),
        sourceHead=value["sourceHead"],
        originalPathsRestoredOnlyInReplica=True,
        incidentBefore={"state": identity(state_path), "events": identity(events), "ledgerRecords": len(ledger)},
    )

    def protected():
        return {key: identity(contained(source, value[key]["path"])) for key in ("state", "eventLog")}

    base = [sys.executable, "-B", "-m", "agent_lifecycle", "workflow"]
    common = ["--state", str(state_path), "--source-revision", before["sourceRevision"]]
    for name, argv, expected in (
        (
            "migration",
            [
                *base,
                "state-migrate",
                *common,
                "--target-schema",
                "agent-workflow-state.v5",
                "--expected-revision",
                "64",
                "--operation-id",
                "isolated-rmk-storage-migrate",
            ],
            0,
        ),
        (
            "expiredRefusal",
            [
                *base,
                "task-start",
                *common,
                "--task",
                "WS-GUARDS",
                "--expected-revision",
                "65",
                "--operation-id",
                "isolated-rmk-expired-refusal",
                "--reason",
                "isolated expired grant refusal only",
            ],
            2,
        ),
    ):
        report.setdefault("containment", []).append(authority_containment(replica, state_path))
        previous = {"state": identity(state_path), "events": identity(events)}
        code, output = run_child(argv, replica, deadline, observations, protected, env)
        report.setdefault("nativeOutcomes", []).append(
            {
                "name": name,
                "expectedExit": expected,
                "actualExit": code,
                "replicaBefore": previous,
                "replicaAfter": {"state": identity(state_path), "events": identity(events)},
            }
        )
        if code != expected or not observations[-1]["protectedStable"]:
            raise ValueError(f"{name} unexpected result/external protected drift")
        after = json.loads(state_path.read_bytes())
        if name == "migration":
            verify_migration(replica, before, after, events, old_events, report)
            report["migration"] = {
                "schema": after["schemaVersion"],
                "phase": after["phase"],
                "state": identity(state_path),
                "events": identity(events),
                "preservedTaskCount": len(after["tasks"]),
            }
        elif "authorization-expired" not in output or previous != {
            "state": identity(state_path),
            "events": identity(events),
        }:
            raise ValueError("expired refusal changed authority or wrong refusal")
        report[name + "Observed"] = True
    report.update(
        status="PASS",
        claim="isolated incident64 migration and expired authorization refusal only",
        liveAcceptance=False,
        renewalPerformed=False,
    )


def verify_migration(replica, before, after, events, old_events, report) -> None:
    from agent_lifecycle.contracts.workflow_storage import iter_historical_snapshots
    from agent_lifecycle.contracts.workflow_storage_context import StorageOperation

    migration = after["storageMigration"]
    backup_path = contained(replica, migration["backupPath"])
    if identity(backup_path) != report["incidentBefore"]["state"] or not events.read_bytes().startswith(old_events):
        raise ValueError("exact backup or original append-only event prefix differs")
    if after["schemaVersion"] != "agent-workflow-state.v5" or after["stateRevision"] != 65:
        raise ValueError("wrong migration target schema/revision")
    if len(after["operationLedger"]) != len(before["operationLedger"]) + 1 or any(
        after["operationLedger"].get(key) != item for key, item in before["operationLedger"].items()
    ):
        raise ValueError("migration changed original operation ledger")
    changed = {
        "schemaVersion",
        "stateRevision",
        "updatedAt",
        "operationLedger",
        "storage",
        "storageMigration",
        "tasks",
        "priorSnapshots",
    }
    for key, item in before.items():
        if key not in changed and after.get(key) != item:
            raise ValueError(f"migration changed preserved field {key}")
    with StorageOperation(replica) as operation:
        tasks = _logical_storage_value(replica, after, after["tasks"], operation)
        snapshots = _logical_storage_value(
            replica,
            after,
            list(iter_historical_snapshots(replica, after, operation=operation)),
            operation,
        )
    if tasks != before["tasks"]:
        raise ValueError("migration changed task data")
    if snapshots != before.get("priorSnapshots", []):
        raise ValueError("migration changed historical snapshots")


def _logical_storage_value(root, state, value, operation):
    """Compare complete logical data through the guarded shared object reader."""
    from agent_lifecycle.contracts.workflow_storage import load_object
    from agent_lifecycle.contracts.workflow_storage_schemas import is_storage_reference

    if is_storage_reference(value):
        value = load_object(root, state, value, operation=operation)
    if isinstance(value, dict):
        return {key: _logical_storage_value(root, state, item, operation) for key, item in value.items()}
    if isinstance(value, list):
        return [_logical_storage_value(root, state, item, operation) for item in value]
    return value


def isolated_environment(runtime: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        PYTHONPATH=str(runtime / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    return env


def supervised(args: argparse.Namespace) -> int:
    """A separate process enforces the whole 300-second ceiling, including I/O."""
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"]
    started = datetime.now(UTC).isoformat()
    child = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=os.name != "nt"
    )
    try:
        stdout, stderr = child.communicate(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(child.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, check=False)
            child.kill()
        stdout, stderr = child.communicate()
        report = {
            "schemaVersion": "workflow-storage-rehearsal.v1",
            "status": "FAIL",
            "startedAt": started,
            "endedAt": datetime.now(UTC).isoformat(),
            "error": "whole-process-timeout",
            "supervisorArgv": argv,
            "stdout": stdout,
            "stderr": stderr,
            "partialObservations": str(args.out) + ".observations.jsonl",
            "liveAcceptance": False,
        }
        if not args.out.exists():
            args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "FAIL", "error": "whole-process-timeout", "out": str(args.out)}))
        return 2
    print(stdout, end="")
    print(stderr, end="", file=sys.stderr)
    return child.returncode


def main(argv=None) -> int:
    global _PARTIAL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["rmk-migration"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--replica-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    report: dict[str, Any] = {
        "schemaVersion": "workflow-storage-rehearsal.v1",
        "status": "FAIL",
        "startedAt": datetime.now(UTC).isoformat(),
    }
    safe_output = True
    try:
        if args.out.exists() or args.out.is_symlink():
            safe_output = False
            raise ValueError("output must be a fresh ordinary file")
        if not 0 < args.timeout_seconds <= 300:
            raise ValueError("timeout must be within 1..300 seconds")
        raw = json.loads(args.input.read_bytes())
        for key in ("sourceRoot", "backupRoot"):
            if isinstance(raw, dict) and isinstance(raw.get(key), str):
                protected_root = Path(raw[key]).resolve()
                if args.out.resolve().is_relative_to(protected_root):
                    safe_output = False
                    raise ValueError("output overlaps protected input root")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if not args._worker:
            return supervised(args)
        _PARTIAL = Path(str(args.out) + ".observations.jsonl")
        if _PARTIAL.exists() or _PARTIAL.is_symlink():
            raise ValueError("partial observations must be fresh")
        rehearse(args, report)
    except (ValueError, OSError, KeyError, TypeError, TimeoutError, json.JSONDecodeError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    report["endedAt"] = datetime.now(UTC).isoformat()
    if safe_output:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, sort_keys=True, indent=2)
            handle.write("\n")
    print(json.dumps({"status": report["status"], "out": str(args.out), "error": report.get("error")}))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
