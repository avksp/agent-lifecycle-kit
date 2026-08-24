"""Project-local profile commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions import START_MODES
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    read_json_object,
    write_json_create,
)
from agent_lifecycle.contracts.project_profile_schemas import PROJECT_PROFILE_STAGES
from agent_lifecycle.host_protocol.lifecycle_control_qualification import validate_capability_level_claims
from agent_lifecycle.project import (
    PROJECT_PROFILE_RELATIVE_PATH,
    build_default_project_profile,
    build_effective_project_profile,
    inspect_project_preset,
    list_project_presets,
    load_project_preset,
    load_project_profile,
    render_project_preset,
    validate_project_preset,
    validate_project_principles,
)


def add_project_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register project-local configuration commands on the root parser."""

    project = subparsers.add_parser("project", help="project-local ALK configuration")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    profile = project_sub.add_parser("profile", help="project workflow profile commands")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    init = profile_sub.add_parser("init", help="create a minimal local project profile")
    init.add_argument("--project-root", default=".")
    init.add_argument("--out", default=".alk/project-profile.json")
    init.add_argument("--adapter", help="set the default adapter in the new profile")
    check = profile_sub.add_parser("check", help="validate and resolve a project profile")
    check.add_argument("--project-root", default=".")
    check.add_argument("--profile")
    check.add_argument("--manifest")
    check.add_argument("--lock")
    check.add_argument("--adapter")
    check.add_argument("--mode", choices=list(START_MODES))
    check.add_argument("--risk", choices=["auto", "S0", "S1", "S2"])
    check.add_argument("--out")
    explain = profile_sub.add_parser("explain", help="explain effective project configuration and evidence level")
    explain.add_argument("--project-root", default=".")
    explain.add_argument("--profile", required=True)
    explain.add_argument("--preset")
    explain.add_argument("--manifest", required=True)
    explain.add_argument("--lock", required=True)
    explain.add_argument("--descriptor", required=True)
    explain.add_argument("--capability-manifest", required=True)
    explain.add_argument("--adapter")
    explain.add_argument("--mode", choices=list(START_MODES))
    explain.add_argument("--risk", choices=["auto", "S0", "S1", "S2"])
    explain.add_argument("--stage-risk", action="append", default=[])
    explain.add_argument("--stage-mode", action="append", default=[])
    explain.add_argument("--out")
    principles = project_sub.add_parser("principles", help="check a bounded project-principles artifact")
    principles_sub = principles.add_subparsers(dest="principles_command", required=True)
    principles_check = principles_sub.add_parser("check", aliases=["validate"])
    principles_check.add_argument("--file", "--path", dest="principles_path", required=True)
    principles_check.add_argument("--project-root", default=".")
    principles_check.add_argument("--out")
    preset = project_sub.add_parser("preset", help="inspect and render built-in workflow presets")
    preset_sub = preset.add_subparsers(dest="preset_command", required=True)
    preset_sub.add_parser("list", help="list built-in workflow presets")
    for command in ("inspect", "validate"):
        child = preset_sub.add_parser(command, help=f"{command} a built-in workflow preset")
        child.add_argument("--preset", required=True)
        child.add_argument("--project-root", default=".")
    render = preset_sub.add_parser("render", help="render a preset to an explicit profile path")
    render.add_argument("--preset", required=True)
    render.add_argument("--project-root", default=".")
    render.add_argument("--profile-id")
    render.add_argument("--adapter")
    render.add_argument("--out", required=True)


def dispatch_project(args: argparse.Namespace) -> dict[str, Any]:
    if args.project_command == "principles":
        if args.principles_command not in {"check", "validate"}:
            raise LifecycleError("command-not-implemented", "project principles command is not implemented")
        return _check_principles(args)
    if args.project_command == "preset":
        return _dispatch_preset(args)
    if args.project_command != "profile":
        raise LifecycleError("command-not-implemented", "project command is not implemented")
    if args.profile_command == "init":
        return _init_profile(args)
    if args.profile_command == "check":
        return _check_profile(args)
    if args.profile_command == "explain":
        return _explain_profile(args)
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
            raise LifecycleError(
                "project-profile-missing",
                "explicit project profile was not found",
                {"path": str(explicit_path)},
            )
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


def _explain_profile(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.project_root).resolve()
    profile, _path = discover_project_profile(project_root=root, explicit_path=args.profile)
    if profile is None:
        raise LifecycleError("project-profile-missing", "explicit project profile was not found")
    plan = _read_project_input(root, args.manifest, label="plan manifest")
    lock = _read_project_input(root, args.lock, label="plan lock")
    preset = load_project_preset(args.preset, project_root=root) if args.preset else None
    overrides = _profile_overrides(args)
    effective = build_effective_project_profile(
        profile,
        preset=preset,
        plan=plan,
        lock=lock,
        cli_overrides=overrides,
        project_root=root,
    )

    descriptor, descriptor_error = _try_read_project_input(root, args.descriptor, label="adapter descriptor")
    capability_manifest, capability_error = _try_read_project_input(
        root, args.capability_manifest, label="capability manifest"
    )
    descriptor_validation: dict[str, Any] | None = None
    capability_validation: dict[str, Any] | None = None
    level_validation: dict[str, Any] | None = None
    if descriptor is not None:
        from agent_lifecycle.host_protocol.validation import validate_adapter_descriptor

        descriptor_validation = validate_adapter_descriptor(descriptor)
    if descriptor is not None and capability_manifest is not None and descriptor_validation is not None:
        from agent_lifecycle.host_protocol.capabilities import validate_capability_manifest

        capability_validation = validate_capability_manifest(capability_manifest, descriptor=descriptor)
        level_validation = validate_capability_level_claims(capability_manifest, descriptor=descriptor)

    descriptor_status = (
        "PASS" if descriptor_validation and descriptor_validation.get("status") == "PASS" else "UNAVAILABLE"
    )
    capability_status = (
        "PASS"
        if capability_validation
        and capability_validation.get("status") == "PASS"
        and level_validation
        and level_validation.get("status") == "PASS"
        else "UNAVAILABLE"
    )
    levels = level_validation.get("levels", {}) if capability_status == "PASS" and level_validation else {}
    fields = _apply_enforceability(effective.get("fieldProvenance", []), levels, capability_status)
    effective_body = {key: value for key, value in effective.items() if key != "effectiveProfileDigest"}
    effective_body["fieldProvenance"] = fields
    effective_profile = {**effective_body, "effectiveProfileDigest": canonical_digest(effective_body)}

    blockers: list[dict[str, Any]] = []
    if descriptor_status != "PASS":
        blockers.append(
            {
                "code": "project-profile-descriptor-unavailable",
                "causes": _validation_codes(descriptor_validation, descriptor_error),
            }
        )
    if capability_status != "PASS":
        blockers.append(
            {
                "code": "project-profile-capability-unavailable",
                "causes": _validation_codes(
                    capability_validation, capability_error
                )
                + _validation_codes(level_validation, None),
            }
        )
    descriptor_lineage = {
        "status": descriptor_status,
        "adapterId": descriptor.get("adapterId") if descriptor else None,
        "host": descriptor.get("host") if descriptor else None,
        "descriptorDigest": canonical_digest(descriptor) if descriptor else None,
        "validationDigest": canonical_digest(descriptor_validation) if descriptor_validation else None,
    }
    capability_lineage = {
        "status": capability_status,
        "adapterId": capability_manifest.get("adapterId") if capability_manifest else None,
        "host": capability_manifest.get("host") if capability_manifest else None,
        "descriptorDigest": capability_manifest.get("descriptorDigest") if capability_manifest else None,
        "capabilityDigest": _capability_digest(capability_manifest),
        "levelValidation": level_validation or {"status": "UNAVAILABLE", "levels": {}, "blockers": []},
    }
    body = {
        "schemaVersion": "agent-effective-configuration-explanation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "effectiveProfile": effective_profile,
        "fields": fields,
        "descriptorLineage": descriptor_lineage,
        "capabilityLineage": capability_lineage,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    result = {**body, "explanationDigest": canonical_digest(body)}
    if args.out:
        output = Path(args.out)
        if not output.is_absolute():
            output = root / output
        _ensure_output_contained(output, root)
        write_json_create(output, result)
    return result


def _profile_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.adapter is not None:
        overrides["defaultAdapter"] = args.adapter
    if args.mode is not None:
        overrides["defaultMode"] = args.mode
    if args.risk is not None:
        overrides["defaultRisk"] = args.risk
    stages: dict[str, dict[str, str]] = {}
    for raw, field in [
        *((value, "risk") for value in args.stage_risk),
        *((value, "mode") for value in args.stage_mode),
    ]:
        if not isinstance(raw, str) or "=" not in raw:
            raise LifecycleError("project-profile-stage-override-invalid", "stage override must use stage=value")
        stage, value = raw.split("=", 1)
        if stage not in PROJECT_PROFILE_STAGES or not value:
            raise LifecycleError("project-profile-stage-override-invalid", "stage override is unsupported")
        stages.setdefault(stage, {})[field] = value
    if stages:
        overrides["stages"] = stages
    return overrides


def _read_project_input(root: Path, raw_path: str, *, label: str) -> dict[str, Any]:
    path = _contained_input_path(root, raw_path, label=label)
    return read_json_object(path, label=label)


def _try_read_project_input(
    root: Path, raw_path: str, *, label: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        return _read_project_input(root, raw_path, label=label), None
    except LifecycleError as exc:
        return None, {"code": exc.code}


def _contained_input_path(root: Path, raw_path: str, *, label: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    if not _is_relative_to(resolved, root):
        raise LifecycleError("project-profile-input-escape", f"{label} must stay inside the project root")
    if path.is_symlink():
        raise LifecycleError("project-profile-input-symlink", f"{label} must not be a symlink")
    return path


def _validation_codes(value: dict[str, Any] | None, error: dict[str, Any] | None) -> list[str]:
    codes: list[str] = []
    if error and isinstance(error.get("code"), str):
        codes.append(error["code"])
    if value:
        for blocker in value.get("blockers", []):
            if isinstance(blocker, dict) and isinstance(blocker.get("code"), str):
                codes.append(blocker["code"])
    return sorted(set(codes))


def _capability_digest(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    from agent_lifecycle.host_protocol.capabilities import capability_manifest_identity

    return capability_manifest_identity(value)


def _apply_enforceability(
    fields: Any,
    levels: dict[str, Any],
    capability_status: str,
) -> list[dict[str, Any]]:
    if not isinstance(fields, list):
        return []
    result: list[dict[str, Any]] = []
    for item in fields:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        operation = _operation_for_field(field) if isinstance(field, str) else None
        enforceability = (
            levels.get(operation, "UNAVAILABLE")
            if capability_status == "PASS" and operation is not None
            else "UNAVAILABLE"
        )
        result.append({**item, "enforceability": enforceability})
    return result


def _operation_for_field(field: str) -> str:
    if field.startswith("stages.finalization"):
        return "final-audit"
    if field.startswith("stages.audit") or field.startswith("stages.review"):
        return "task-audit"
    return "adapter-event-stream"


def _check_principles(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.project_root).resolve()
    source = Path(args.principles_path)
    if not source.is_absolute():
        source = root / source
    try:
        payload = read_json_object(source, label="project principles")
    except OSError as exc:
        raise LifecycleError(
            "project-principles-read-failed",
            "project principles cannot be read",
            {"path": str(args.principles_path)},
        ) from exc
    result = validate_project_principles(payload, project_root=root, source_path=source)
    if args.out:
        write_json_create(Path(args.out), result)
    return result


def _dispatch_preset(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(getattr(args, "project_root", ".")).resolve()
    if args.preset_command == "list":
        return list_project_presets(project_root=root)
    if args.preset_command == "inspect":
        return inspect_project_preset(args.preset, project_root=root)
    if args.preset_command == "validate":
        preset = load_project_preset(args.preset, project_root=root)
        return validate_project_preset(preset)
    if args.preset_command == "render":
        output = Path(args.out)
        if not output.is_absolute():
            output = root / output
        _ensure_output_contained(output, root)
        return render_project_preset(
            args.preset,
            output_path=output,
            project_root=root,
            profile_id=args.profile_id,
            default_adapter=args.adapter,
        )
    raise LifecycleError("command-not-implemented", "project preset command is not implemented")


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
