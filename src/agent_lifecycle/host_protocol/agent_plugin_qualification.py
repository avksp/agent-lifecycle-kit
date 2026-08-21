"""Agent Plugins qualification helpers.

Offline verification is kept in pure local functions. Host execution is
limited to the explicit probe helpers and is checked by a dedicated AST
boundary validator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, sha256_hex
from agent_lifecycle.contracts.agent_plugin_qualification_schemas import (
    CANONICAL_SKILLS,
    PROFILE_SCHEMA,
    RECEIPT_SCHEMA,
    build_qualification_receipt,
    validate_qualification_profile,
    validate_qualification_receipt,
)
from agent_lifecycle.contracts.process_redaction import redact_process_text


def package_identity(package_root: Path) -> dict[str, Any]:
    """Return a deterministic file inventory without exposing file contents."""

    root = package_root.resolve()
    if not root.is_dir():
        raise LifecycleError("plugin-package-missing", "package root does not exist", {"path": package_root.as_posix()})
    files: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_hex(data),
                "bytes": len(data),
            }
        )
    return {
        "fileCount": len(files),
        "totalBytes": sum(item["bytes"] for item in files),
        "files": files,
        "packageDigest": canonical_digest(files),
    }


def build_offline_qualification_receipt(
    *,
    package_root: Path,
    profile: dict[str, Any],
    package_result: dict[str, Any],
) -> dict[str, Any]:
    """Build the receipt for a package-only, zero-process verification."""

    profile_validation = validate_qualification_profile(profile)
    identity = package_identity(package_root)
    manifest_path = package_root / "plugin.json"
    package_version: str | None = None
    manifest_check: dict[str, Any] = {
        "name": "package-manifest",
        "status": "FAIL",
        "details": {"path": "plugin.json"},
    }
    try:
        manifest = read_json_object(manifest_path, label="portable plugin manifest")
        package_version = manifest.get("version") if isinstance(manifest.get("version"), str) else None
        manifest_check = {
            "name": "package-manifest",
            "status": "PASS" if manifest.get("name") == "agent-lifecycle-kit" else "FAIL",
            "details": {"name": manifest.get("name"), "version": package_version},
        }
    except (OSError, LifecycleError) as exc:
        manifest_check["details"]["reason"] = getattr(exc, "code", type(exc).__name__)

    blockers = list(profile_validation.get("blockers", []))
    blockers.extend(package_result.get("blockers", []))
    if manifest_check["status"] != "PASS":
        blockers.append({"code": "plugin-manifest-check-failed"})
    skill_names = package_result.get("skillNames", [])
    if skill_names != list(CANONICAL_SKILLS):
        blockers.append({"code": "plugin-skill-set-mismatch", "expected": list(CANONICAL_SKILLS), "actual": skill_names})
    checks = [
        {"name": "profile", "status": profile_validation["status"]},
        {"name": "package", "status": package_result.get("status", "FAIL")},
        manifest_check,
        {"name": "host-processes", "status": "PASS", "details": {"processCalls": 0}},
        {"name": "model-and-network-calls", "status": "PASS", "details": {"modelCalls": 0, "networkCalls": 0}},
    ]
    return build_qualification_receipt(
        profile=profile,
        status="OFFLINE_VALIDATED" if not blockers else "BLOCKED",
        package_version=package_version,
        package_digest=identity["packageDigest"],
        package_skill_count=len(skill_names) if isinstance(skill_names, list) else 0,
        checks=checks,
        process_calls=0,
        blockers=blockers,
    )


def validate_offline_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Expose receipt validation for release tools and contract tests."""

    validation = validate_qualification_receipt(receipt)
    if receipt.get("schemaVersion") != RECEIPT_SCHEMA:
        validation["blockers"].append({"code": "receipt-schema-mismatch"})
        validation["status"] = "FAIL"
    if receipt.get("status") not in {"OFFLINE_VALIDATED", "BLOCKED"}:
        validation["blockers"].append({"code": "offline-status-invalid", "status": receipt.get("status")})
        validation["status"] = "FAIL"
    validation_body = {key: value for key, value in validation.items() if key != "validationDigest"}
    return {**validation_body, "validationDigest": canonical_digest(validation_body)}


def run_agent_plugin_qualification_probe(
    *,
    package_root: Path,
    project_root: Path,
    profile: dict[str, Any],
    host_bin: str | None = None,
    command_runner: Any | None = None,
) -> dict[str, Any]:
    """Run the explicit, read-only client probe described by a profile."""

    profile_validation = validate_qualification_profile(profile)
    if profile_validation["status"] != "PASS":
        raise LifecycleError("plugin-qualification-profile-invalid", "qualification profile failed validation", profile_validation)
    if profile["qualification"]["status"] != "SUPPORTED":
        return build_qualification_receipt(
            profile=profile,
            status="UNAVAILABLE",
            package_version=None,
            package_digest=None,
            package_skill_count=0,
            checks=[{"name": "profile-support", "status": "UNAVAILABLE"}],
            blockers=[{"code": "client-qualification-unavailable"}],
        )

    package_checks, package_version, package_skill_count, package_digest, package_blockers = _inspect_package(package_root, profile)
    project_checks, project_blockers = _inspect_project(project_root, profile, expected_version=package_version)
    checks = [*package_checks, *project_checks]
    process_calls = 0
    client_version: str | None = None
    host_checks: list[dict[str, Any]] = []
    host_name = Path(host_bin or profile["host"]).name
    runner = command_runner or _default_probe_runner(profile, project_root)
    for name, arguments in (
        ("client-version", profile["discovery"]["versionArgs"]),
        ("client-help", profile["discovery"]["helpArgs"]),
    ):
        process_calls += 1
        result = _run_probe_command(runner, [host_bin or profile["host"], *arguments], profile)
        text = "\n".join(part for part in (result.get("stdout", ""), result.get("stderr", "")) if part)
        first_line = _first_line(text) if result.get("status") == "PASS" else None
        if name == "client-version" and first_line:
            client_version = first_line[:120]
        host_checks.append(
            {
                "name": name,
                "status": "PASS" if result.get("status") == "PASS" else "FAIL",
                "details": {
                    "binary": host_name,
                    "exitCode": result.get("exitCode"),
                    "timedOut": bool(result.get("timedOut")),
                    "stdoutBytes": len(result.get("stdout", "").encode("utf-8")),
                    "stderrBytes": len(result.get("stderr", "").encode("utf-8")),
                    "stdoutSha256": sha256_hex(result.get("stdout", "").encode("utf-8")),
                    "stderrSha256": sha256_hex(result.get("stderr", "").encode("utf-8")),
                    "firstLine": first_line[:120] if first_line else None,
                },
            }
        )
        if result.get("status") != "PASS":
            host_checks[-1]["details"]["blockers"] = result.get("blockers", [])

    checks.extend(host_checks)
    host_blockers = [
        {"code": "client-probe-failed", "operation": item["name"], "details": item["details"]}
        for item in host_checks
        if item["status"] != "PASS"
    ]
    blockers = [*package_blockers, *project_blockers, *host_blockers]
    unavailable = any(
        issue.get("code") in {"adapter-process-start-failed", "binary-not-found"}
        for item in host_checks
        for issue in item.get("details", {}).get("blockers", [])
        if isinstance(issue, dict)
    )
    status = "QUALIFIED" if not blockers else ("UNAVAILABLE" if unavailable else "BLOCKED")
    return build_qualification_receipt(
        profile=profile,
        status=status,
        package_version=package_version,
        package_digest=package_digest,
        package_skill_count=package_skill_count,
        checks=checks,
        process_calls=process_calls,
        client_version=client_version,
        blockers=blockers,
    )


def _inspect_package(package_root: Path, profile: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None, int, str | None, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    package_version: str | None = None
    package_skill_count = 0
    package_digest: str | None = None
    try:
        identity = package_identity(package_root)
        package_digest = identity["packageDigest"]
        manifest = read_json_object(package_root / profile["package"]["manifestPath"], label="portable plugin manifest")
        package_version = manifest.get("version") if isinstance(manifest.get("version"), str) else None
        manifest_ok = manifest.get("name") == profile["package"]["name"]
        checks.append({"name": "portable-package-manifest", "status": "PASS" if manifest_ok else "FAIL", "details": {"name": manifest.get("name"), "version": package_version}})
        if not manifest_ok:
            blockers.append({"code": "portable-package-name-mismatch"})
        skills_root = package_root / profile["package"]["skillsPath"]
        actual = sorted(item.name for item in skills_root.iterdir() if item.is_dir()) if skills_root.is_dir() else []
        package_skill_count = len(actual)
        expected = list(profile["package"]["requiredSkills"])
        skills_ok = actual == expected
        checks.append({"name": "portable-package-skills", "status": "PASS" if skills_ok else "FAIL", "details": {"skillCount": package_skill_count, "requiredSkillCount": len(expected)}})
        if not skills_ok:
            blockers.append({"code": "portable-package-skill-set-mismatch", "expected": expected, "actual": actual})
    except (OSError, LifecycleError) as exc:
        blockers.append({"code": "portable-package-inspection-failed", "errorType": type(exc).__name__})
        checks.append({"name": "portable-package", "status": "FAIL", "details": {"errorType": type(exc).__name__}})
    return checks, package_version, package_skill_count, package_digest, blockers


def _inspect_project(
    project_root: Path,
    profile: dict[str, Any],
    *,
    expected_version: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = project_root.resolve()
    discovery = profile["discovery"]
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    manifest_path = root / discovery["pluginManifestPath"]
    try:
        manifest = read_json_object(manifest_path, label="client plugin projection")
        name_matched = manifest.get("name") == profile["package"]["name"]
        version_matched = expected_version is None or manifest.get("version") == expected_version
        matched = name_matched and version_matched
        checks.append(
            {
                "name": "client-plugin-projection",
                "status": "PASS" if matched else "FAIL",
                "details": {
                    "path": discovery["pluginManifestPath"],
                    "version": manifest.get("version"),
                    "expectedVersion": expected_version,
                },
            }
        )
        if not matched:
            blockers.append(
                {
                    "code": "client-plugin-projection-mismatch",
                    "nameMatched": name_matched,
                    "versionMatched": version_matched,
                }
            )
    except (OSError, LifecycleError) as exc:
        checks.append({"name": "client-plugin-projection", "status": "FAIL", "details": {"path": discovery["pluginManifestPath"], "errorType": type(exc).__name__}})
        blockers.append({"code": "client-plugin-projection-missing"})
    skills_root = root / discovery["skillsPath"]
    missing = [skill for skill in profile["package"]["requiredSkills"] if not (skills_root / skill / "SKILL.md").is_file()]
    checks.append({"name": "client-skill-discovery", "status": "PASS" if not missing else "FAIL", "details": {"path": discovery["skillsPath"], "missing": missing}})
    if missing:
        blockers.append({"code": "client-skills-missing", "missing": missing})
    return checks, blockers


def _default_probe_runner(profile: dict[str, Any], project_root: Path) -> Any:
    """Return a fail-closed runner when no composition adapter was supplied."""

    def runner(argv: list[str], _timeout: float) -> dict[str, Any]:
        return {
            "status": "FAIL",
            "exitCode": None,
            "timedOut": False,
            "stdout": "",
            "stderr": "",
            "blockers": [{"code": "qualification-runner-required"}],
        }

    return runner


def _run_probe_command(runner: Any, argv: list[str], profile: dict[str, Any]) -> dict[str, Any]:
    try:
        result = runner(argv, float(profile["qualification"]["timeoutSeconds"]))
    except FileNotFoundError:
        return {"status": "FAIL", "exitCode": None, "timedOut": False, "stdout": "", "stderr": "", "blockers": [{"code": "binary-not-found"}]}
    except Exception as exc:  # pragma: no cover - defensive host boundary
        return {"status": "FAIL", "exitCode": None, "timedOut": False, "stdout": "", "stderr": "", "blockers": [{"code": "probe-runner-failed", "errorType": type(exc).__name__}]}
    if hasattr(result, "returncode"):
        stdout, _ = redact_process_text(str(getattr(result, "stdout", "") or ""))
        stderr, _ = redact_process_text(str(getattr(result, "stderr", "") or ""))
        return {
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "exitCode": result.returncode,
            "timedOut": False,
            "stdout": stdout,
            "stderr": stderr,
            "blockers": [] if result.returncode == 0 else [{"code": "client-process-nonzero", "exitCode": result.returncode}],
        }
    if isinstance(result, dict):
        # run_process returns redacted stdoutTail/stderrTail for its bounded
        # receipt path. Keep the probe contract independent from that helper's
        # internal field names and never persist raw host output.
        stdout, _ = redact_process_text(str(result.get("stdout", result.get("stdoutTail", ""))))
        stderr, _ = redact_process_text(str(result.get("stderr", result.get("stderrTail", ""))))
        return {
            **result,
            "stdout": stdout,
            "stderr": stderr,
        }
    return result


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def profile_schema_id() -> str:
    return PROFILE_SCHEMA
