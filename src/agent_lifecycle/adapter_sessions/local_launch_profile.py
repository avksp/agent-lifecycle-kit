"""Validation and rendering for operator-local host launch profiles."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.adapter_sessions.qualification import validate_qualification_policy

LOCAL_HOST_LAUNCH_PROFILE_SCHEMA = "agent-local-host-launch-profile.v1"
LOCAL_HOST_LAUNCH_PROFILE_VALIDATION_SCHEMA = "agent-local-host-launch-profile-validation.v1"
PLANNING_ONLY_PROFILE_SCHEMA = "agent-planning-only-launch-profile.v1"
LOCAL_PROFILE_ROOT = Path(".alk/host-launch")
MAX_PROFILE_BYTES = 32768
MAX_TIMEOUT_SECONDS = 300.0
MAX_ARGV_ITEMS = 64
MAX_ARG_BYTES = 4096
EXECUTABLE_HASH_CHUNK_BYTES = 256 * 1024
SAFE_VERSION_PROBES = (("--version",), ("-V",), ("version",))
PLANNING_SUPPORT_STATUSES = frozenset(
    {"PLANNING_ONLY_QUALIFIED", "PLANNING_ONLY_UNSUPPORTED"}
)
_DANGEROUS_PLANNING_FLAGS = frozenset(
    {
        "--allow-dangerously-skip-permissions",
        "--auto",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-skip-permissions",
        "--full-auto",
        "--yolo",
    }
)

ALLOWED_LAUNCH_PLACEHOLDERS = frozenset(
    {
        "adapter_id",
        "lock_path",
        "manifest_path",
        "operation_id",
        "risk_profile_digest",
        "source_revision",
        "state_path",
        "task_id",
    }
)

_ADAPTER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
_SHELL_EXECUTABLES = frozenset(
    {
        "bash",
        "cmd",
        "cmd.exe",
        "dash",
        "fish",
        "ksh",
        "powershell",
        "powershell.exe",
        "pwsh",
        "sh",
        "zsh",
    }
)


def load_local_launch_profile(
    profile_path: Path,
    *,
    project_root: Path | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Load a validated profile contained below the ignored local root."""

    lexical_root = (project_root or Path.cwd()).absolute()
    root = lexical_root.resolve()
    local_root_path = lexical_root / LOCAL_PROFILE_ROOT
    candidate = profile_path if profile_path.is_absolute() else lexical_root / profile_path
    try:
        lexical_candidate = candidate.absolute()
        lexical_candidate.relative_to(local_root_path)
        _reject_symlink_components(lexical_root, lexical_candidate)
        local_root = local_root_path.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(local_root)
    except (OSError, ValueError) as exc:
        raise LifecycleError(
            "local-launch-profile-path-outside-root",
            "local launch profile must resolve below .alk/host-launch",
        ) from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise LifecycleError(
            "local-launch-profile-path-invalid",
            "local launch profile must be a regular, non-symlink file",
        )
    if resolved.stat().st_size > MAX_PROFILE_BYTES:
        raise LifecycleError(
            "local-launch-profile-too-large",
            f"local launch profile exceeds {MAX_PROFILE_BYTES} bytes",
        )
    profile = read_json_object(resolved, label="local host launch profile")
    validation = validate_local_launch_profile(profile)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "local-launch-profile-invalid",
            "local host launch profile failed validation",
            {"validation": validation},
        )
    return LOCAL_PROFILE_ROOT / relative, profile, validation


def validate_local_launch_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate a closed, operator-local process launch declaration."""

    blockers: list[dict[str, Any]] = []
    if profile.get("schemaVersion") != LOCAL_HOST_LAUNCH_PROFILE_SCHEMA:
        blockers.append({"code": "local-launch-profile-schema"})
    if profile.get("status") != "LOCAL_OPT_IN":
        blockers.append({"code": "local-launch-profile-status"})

    adapter_id = profile.get("adapterId")
    if not isinstance(adapter_id, str) or not _ADAPTER_ID.fullmatch(adapter_id):
        blockers.append({"code": "local-launch-profile-adapter"})

    executable = profile.get("executable")
    if not _valid_executable(executable):
        blockers.append({"code": "local-launch-profile-executable"})
    elif _executable_name(executable).lower() in _SHELL_EXECUTABLES:
        blockers.append({"code": "local-launch-profile-shell-executable"})

    _validate_argv_template(profile.get("argvTemplate"), field="argvTemplate", placeholders=True, blockers=blockers)
    _validate_argv_template(
        profile.get("versionProbeArgs"),
        field="versionProbeArgs",
        placeholders=False,
        blockers=blockers,
        require_non_empty=True,
    )
    version_probe = profile.get("versionProbeArgs")
    if isinstance(version_probe, list) and tuple(version_probe) not in SAFE_VERSION_PROBES:
        blockers.append({"code": "local-launch-profile-version-probe"})
    _validate_env(profile.get("env"), blockers)
    _validate_planning_only(profile.get("planningOnly"), blockers)
    if isinstance(executable, str) and "/" not in executable and "\\" not in executable:
        if "PATH" not in _env_names(profile):
            blockers.append({"code": "local-launch-profile-path-env-required"})

    timeout = profile.get("timeoutSeconds")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
        or timeout > MAX_TIMEOUT_SECONDS
    ):
        blockers.append(
            {
                "code": "local-launch-profile-timeout",
                "maximumSeconds": MAX_TIMEOUT_SECONDS,
            }
        )

    required_false = (
        "shell",
        "writesNativeConfig",
        "promptInjectionDefault",
        "publicSupportClaimed",
        "productionPromotionClaimed",
    )
    for field in required_false:
        if profile.get(field) is not False:
            blockers.append({"code": "local-launch-profile-safe-default", "field": field})
    blockers.extend(validate_qualification_policy(profile))

    body = {
        "schemaVersion": LOCAL_HOST_LAUNCH_PROFILE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "profileDigest": canonical_digest(profile),
        "adapterId": adapter_id if isinstance(adapter_id, str) else None,
        "allowedPlaceholders": sorted(ALLOWED_LAUNCH_PLACEHOLDERS),
        "blockers": blockers,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_executable_identity(
    profile: dict[str, Any],
    *,
    process_env: dict[str, str] | None = None,
    profile_digest: str | None = None,
    shipped_profile_digest: str | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Bind a launch receipt to the resolved executable without storing its path."""

    executable = str(profile.get("executable", ""))
    source_env = os.environ if process_env is None else process_env
    if Path(executable).is_absolute():
        candidate = Path(executable)
    else:
        path_value = None if process_env is None else source_env.get("PATH", "")
        resolved_name = shutil.which(executable, path=path_value)
        candidate = Path(resolved_name) if resolved_name else None
    origin = "SHIPPED_PROFILE_BOUND" if profile_digest and profile_digest == shipped_profile_digest else "OPERATOR_OWNED_UNVERIFIED"
    base = {
        "schemaVersion": "agent-host-executable-identity.v1",
        "status": "UNAVAILABLE",
        "trustClass": origin,
        "profileOrigin": origin,
        "profileDigest": profile_digest,
        "shippedProfileDigest": shipped_profile_digest,
        "executableName": _executable_name(executable),
        "resolvedPathSha256": None,
        "executableContentSha256": None,
        "executableBytes": None,
        "resolvedFromSymlink": False,
        "pathStored": False,
    }
    if candidate is None:
        if strict:
            raise LifecycleError(
                "local-launch-executable-identity-unavailable",
                "launch executable could not be resolved from the allowlisted environment",
                {"executableName": _executable_name(executable)},
            )
        return {**base, "identityDigest": canonical_digest(base)}
    try:
        resolved = candidate.resolve(strict=True)
        before = resolved.stat()
        if not resolved.is_file():
            raise OSError("executable is not a regular file")
        digest = hashlib.sha256()
        byte_count = 0
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(EXECUTABLE_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                byte_count += len(chunk)
        after = resolved.stat()
    except OSError as exc:
        if strict:
            raise LifecycleError(
                "local-launch-executable-identity-unavailable",
                "launch executable identity could not be read",
                {"executableName": _executable_name(executable), "errorType": type(exc).__name__},
            ) from exc
        return {**base, "identityDigest": canonical_digest(base)}
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if identity_before != identity_after:
        if not strict:
            return {**base, "identityDigest": canonical_digest(base)}
        raise LifecycleError(
            "local-launch-executable-changed",
            "launch executable changed while its identity was captured",
            {"executableName": _executable_name(executable)},
        )
    body = {
        **base,
        "status": "PASS",
        "resolvedPathSha256": hashlib.sha256(os.fsencode(str(resolved))).hexdigest(),
        "executableContentSha256": digest.hexdigest(),
        "executableBytes": byte_count,
        "resolvedFromSymlink": candidate != resolved,
    }
    return {**body, "identityDigest": canonical_digest(body)}


def render_local_launch_argv(profile: dict[str, Any], bindings: dict[str, str]) -> list[str]:
    """Render exact-token placeholders without shell or substring interpolation."""

    validation = validate_local_launch_profile(profile)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "local-launch-profile-invalid",
            "cannot render an invalid local launch profile",
            {"validation": validation},
        )
    argv = [str(profile["executable"])]
    for token in profile["argvTemplate"]:
        match = _PLACEHOLDER.fullmatch(token)
        if match is None:
            argv.append(token)
            continue
        name = match.group(1)
        value = bindings.get(name)
        if not isinstance(value, str) or not value:
            raise LifecycleError(
                "local-launch-binding-missing",
                "local launch placeholder has no frozen binding",
                {"placeholder": name},
            )
        argv.append(value)
    return argv


def render_planning_launch_argv(profile: dict[str, Any]) -> list[str]:
    """Render the fixed planning argv; raw task input is always stdin-only."""

    validation = validate_local_launch_profile(profile)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "local-launch-profile-invalid",
            "cannot render an invalid local launch profile",
            {"validation": validation},
        )
    planning = profile.get("planningOnly")
    if not isinstance(planning, dict) or planning.get("status") != "CANDIDATE":
        raise LifecycleError(
            "planning-launch-profile-unsupported",
            "adapter has no planning-only argv profile",
        )
    template = planning.get("argvTemplate")
    if not isinstance(template, list):
        raise LifecycleError("planning-launch-profile-invalid", "planning argv template is missing")
    return [str(profile["executable"]), *[str(token) for token in template]]


def local_profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted profile view suitable for portable receipts."""

    summary = {
        "schemaVersion": profile.get("schemaVersion"),
        "status": profile.get("status"),
        "adapterId": profile.get("adapterId"),
        "executable": _executable_name(str(profile.get("executable", ""))),
        "argvTemplate": list(profile.get("argvTemplate", [])),
        "versionProbeArgs": list(profile.get("versionProbeArgs", [])),
        "allowedEnvironmentNames": sorted(_env_names(profile)),
        "timeoutSeconds": profile.get("timeoutSeconds"),
        "shell": False,
        "publicSupportClaimed": False,
    }
    planning = profile.get("planningOnly")
    if isinstance(planning, dict):
        summary["planningOnly"] = {
            "schemaVersion": planning.get("schemaVersion"),
            "status": planning.get("status"),
            "planningSupportStatus": planning.get("planningSupportStatus"),
            "argvTemplate": list(planning.get("argvTemplate", [])),
            "inputTransport": planning.get("inputTransport"),
            "resultFormat": planning.get("resultFormat"),
            "containment": planning.get("containment"),
            "qualificationEvidence": list(planning.get("qualificationEvidence", [])),
        }
    qualification = profile.get("qualification")
    if isinstance(qualification, dict):
        summary["qualification"] = {
            "schemaVersion": qualification.get("schemaVersion"),
            "expectedVersion": qualification.get("expectedVersion"),
            "receiptFile": qualification.get("receiptFile"),
            "requiredForManagedTask": qualification.get("requiredForManagedTask"),
            "maxPreflightProcesses": qualification.get("maxPreflightProcesses"),
            "modelCallsForPreflight": qualification.get("modelCallsForPreflight"),
        }
    redacted, _changed = redact_value(summary)
    return redacted


def local_receipt_argv(profile: dict[str, Any]) -> list[str]:
    """Return the template-shaped argv without resolved local binding values."""

    executable = _executable_name(str(profile.get("executable", "")))
    template = profile.get("argvTemplate")
    return [executable, *template] if isinstance(template, list) else [executable]


def planning_receipt_argv(profile: dict[str, Any]) -> list[str]:
    """Return planning argv without local values or task data."""

    executable = _executable_name(str(profile.get("executable", "")))
    planning = profile.get("planningOnly")
    template = planning.get("argvTemplate") if isinstance(planning, dict) else []
    return [executable, *template] if isinstance(template, list) else [executable]


def _valid_executable(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_ARG_BYTES
        or any(character in value for character in ("\x00", "\n", "\r"))
    ):
        return False
    if "/" not in value and "\\" not in value:
        return value not in {".", ".."}
    if value.startswith("/"):
        return ".." not in Path(value).parts
    if re.match(r"^[A-Za-z]:\\", value):
        return ".." not in value.replace("\\", "/").split("/")
    return False


def _executable_name(value: str) -> str:
    return re.split(r"[\\/]", value)[-1]


def _validate_argv_template(
    value: Any,
    *,
    field: str,
    placeholders: bool,
    blockers: list[dict[str, Any]],
    require_non_empty: bool = False,
) -> None:
    if not isinstance(value, list) or (require_non_empty and not value) or len(value) > MAX_ARGV_ITEMS:
        blockers.append({"code": "local-launch-profile-argv", "field": field})
        return
    for index, token in enumerate(value):
        if (
            not isinstance(token, str)
            or not token
            or len(token.encode("utf-8")) > MAX_ARG_BYTES
            or "\x00" in token
            or "\n" in token
            or "\r" in token
        ):
            blockers.append({"code": "local-launch-profile-argv-token", "field": field, "index": index})
            continue
        match = _PLACEHOLDER.fullmatch(token)
        if match is not None:
            name = match.group(1)
            if not placeholders or name not in ALLOWED_LAUNCH_PLACEHOLDERS:
                blockers.append(
                    {
                        "code": "local-launch-profile-placeholder",
                        "field": field,
                        "index": index,
                        "placeholder": name,
                    }
                )
        elif "{" in token or "}" in token:
            blockers.append({"code": "local-launch-profile-placeholder-shape", "field": field, "index": index})


def _validate_env(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "local-launch-profile-env"})
        return
    allow = value.get("allow")
    if not isinstance(allow, list) or not all(isinstance(name, str) and _ENV_NAME.fullmatch(name) for name in allow):
        blockers.append({"code": "local-launch-profile-env-allow"})
    elif len(set(allow)) != len(allow):
        blockers.append({"code": "local-launch-profile-env-duplicate"})
    patterns = value.get("allowPatterns")
    if patterns != []:
        blockers.append({"code": "local-launch-profile-env-pattern"})
    if value.get("projectPolicyAllowed") is not False:
        blockers.append({"code": "local-launch-profile-env-project-policy"})


def _validate_planning_only(value: Any, blockers: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or value.get("schemaVersion") != PLANNING_ONLY_PROFILE_SCHEMA:
        blockers.append({"code": "planning-launch-profile-schema"})
        return
    status = value.get("status")
    support = value.get("planningSupportStatus")
    if status not in {"CANDIDATE", "UNSUPPORTED"}:
        blockers.append({"code": "planning-launch-profile-status"})
    if support not in PLANNING_SUPPORT_STATUSES:
        blockers.append({"code": "planning-launch-support-status"})
    if status == "UNSUPPORTED":
        if support != "PLANNING_ONLY_UNSUPPORTED":
            blockers.append({"code": "planning-launch-unsupported-claim"})
        if value.get("argvTemplate") not in (None, []):
            blockers.append({"code": "planning-launch-unsupported-argv"})
        return
    _validate_argv_template(
        value.get("argvTemplate"),
        field="planningOnly.argvTemplate",
        placeholders=False,
        blockers=blockers,
        require_non_empty=True,
    )
    argv = value.get("argvTemplate") if isinstance(value.get("argvTemplate"), list) else []
    if any(token in _DANGEROUS_PLANNING_FLAGS for token in argv):
        blockers.append({"code": "planning-launch-dangerous-flag"})
    for index, token in enumerate(argv[:-1]):
        if token == "--permission-mode" and argv[index + 1] == "bypassPermissions":
            blockers.append({"code": "planning-launch-dangerous-permission-mode"})
    if value.get("inputTransport") != "STDIN":
        blockers.append({"code": "planning-launch-input-transport"})
    if value.get("resultFormat") != "SINGLE_JSON_OBJECT":
        blockers.append({"code": "planning-launch-result-format"})
    containment = value.get("containment")
    if not isinstance(containment, dict) or containment.get("writesAllowed") is not False:
        blockers.append({"code": "planning-launch-containment"})
    evidence = value.get("qualificationEvidence")
    if not isinstance(evidence, list) or not all(isinstance(item, str) and item for item in evidence):
        blockers.append({"code": "planning-launch-qualification-evidence"})
    if support == "PLANNING_ONLY_QUALIFIED" and not evidence:
        blockers.append({"code": "planning-launch-qualified-evidence-missing"})


def _env_names(profile: dict[str, Any]) -> list[str]:
    env = profile.get("env")
    allow = env.get("allow") if isinstance(env, dict) else []
    return [name for name in allow if isinstance(name, str)] if isinstance(allow, list) else []


def _reject_symlink_components(root: Path, candidate: Path) -> None:
    current = root
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise LifecycleError(
            "local-launch-profile-path-outside-root",
            "local launch profile must resolve below .alk/host-launch",
        ) from exc
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise LifecycleError(
                "local-launch-profile-path-invalid",
                "local launch profile path must not contain symbolic links",
            )
