"""Project-local profile commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
from agent_lifecycle.project import (
    PROJECT_PROFILE_RELATIVE_PATH,
    build_default_project_profile,
    build_effective_project_profile,
    load_project_profile,
)


def dispatch_project(args: argparse.Namespace) -> dict[str, Any]:
    if args.project_command != "profile":
        raise LifecycleError("command-not-implemented", "project command is not implemented")
    if args.profile_command == "init":
        return _init_profile(args)
    if args.profile_command == "check":
        return _check_profile(args)
    raise LifecycleError("command-not-implemented", "project profile command is not implemented")


def discover_project_profile(
    *,
    project_root: Path,
    explicit_path: str | None = None,
    disabled: bool = False,
) -> tuple[dict[str, Any] | None, Path | None]:
    """Select an explicit or conventional profile without searching parents."""

    if disabled:
        return None, None
    root = project_root.resolve()
    path = Path(explicit_path) if explicit_path else root / PROJECT_PROFILE_RELATIVE_PATH
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        if explicit_path:
            raise LifecycleError("project-profile-missing", "explicit project profile was not found", {"path": str(explicit_path)})
        return None, None
    return load_project_profile(path, project_root=root), path


def _init_profile(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.project_root).resolve()
    output = Path(args.out)
    if not output.is_absolute():
        output = root / output
    _ensure_output_contained(output, root)
    profile = build_default_project_profile()
    if args.adapter is not None:
        if not args.adapter.strip():
            raise LifecycleError("project-profile-adapter-invalid", "--adapter must be a non-empty value")
        profile["defaultAdapter"] = args.adapter
    data = write_json_create(output, profile)
    return {
        "schemaVersion": "agent-project-profile-init-receipt.v1",
        "status": "PASS",
        "path": _display_path(output, root),
        "profile": profile,
        "bytesWritten": len(data),
        "productionPromotionClaimed": False,
    }


def _check_profile(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.project_root).resolve()
    profile, _path = discover_project_profile(project_root=root, explicit_path=args.profile)
    if profile is None:
        raise LifecycleError(
            "project-profile-missing",
            "no project profile was found",
            {"initCommand": "agent-lifecycle project profile init --out .alk/project-profile.json"},
        )
    plan = read_json_object(Path(args.manifest), label="plan manifest") if args.manifest else None
    lock = read_json_object(Path(args.lock), label="plan lock") if args.lock else None
    overrides: dict[str, Any] = {}
    if args.adapter is not None:
        overrides["defaultAdapter"] = args.adapter
    if args.mode is not None:
        overrides["defaultMode"] = args.mode
    if args.risk is not None:
        overrides["defaultRisk"] = args.risk
    effective = build_effective_project_profile(
        profile,
        plan=plan,
        lock=lock,
        cli_overrides=overrides,
        project_root=root,
    )
    if args.out:
        write_json_create(Path(args.out), effective)
    return effective


def _ensure_output_contained(path: Path, root: Path) -> None:
    resolved_root = root.resolve()
    parent = path.parent.resolve(strict=False)
    if not _is_relative_to(parent, resolved_root):
        raise LifecycleError("project-profile-output-escape", "profile output must stay inside the project root")
    if path.exists() and path.is_symlink():
        raise LifecycleError("project-profile-output-symlink", "profile output must not be a symlink")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "<project>"
