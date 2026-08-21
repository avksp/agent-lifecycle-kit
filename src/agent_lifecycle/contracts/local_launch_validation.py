"""Pure validation rules for operator-local host launch profiles."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.launch_qualification import validate_qualification_policy

LOCAL_HOST_LAUNCH_PROFILE_SCHEMA = "agent-local-host-launch-profile.v1"
LOCAL_HOST_LAUNCH_PROFILE_VALIDATION_SCHEMA = "agent-local-host-launch-profile-validation.v1"
PLANNING_ONLY_PROFILE_SCHEMA = "agent-planning-only-launch-profile.v1"
MAX_TIMEOUT_SECONDS = 300.0
MAX_ARGV_ITEMS = 64
MAX_ARG_BYTES = 4096
PLANNING_SUPPORT_STATUSES = frozenset({"PLANNING_ONLY_QUALIFIED", "PLANNING_ONLY_UNSUPPORTED"})
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
    {"bash", "cmd", "cmd.exe", "dash", "fish", "ksh", "powershell", "powershell.exe", "pwsh", "sh", "zsh"}
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
SAFE_VERSION_PROBES = (("--version",), ("-V",), ("version",))


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
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
        blockers.append({"code": "local-launch-profile-timeout", "maximumSeconds": MAX_TIMEOUT_SECONDS})
    for field in ("shell", "writesNativeConfig", "promptInjectionDefault", "publicSupportClaimed", "productionPromotionClaimed"):
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


def _valid_executable(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_ARG_BYTES or any(c in value for c in ("\x00", "\n", "\r")):
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
        if not isinstance(token, str) or not token or len(token.encode("utf-8")) > MAX_ARG_BYTES or any(c in token for c in ("\x00", "\n", "\r")):
            blockers.append({"code": "local-launch-profile-argv-token", "field": field, "index": index})
            continue
        match = _PLACEHOLDER.fullmatch(token)
        if match is not None:
            name = match.group(1)
            if not placeholders or name not in ALLOWED_LAUNCH_PLACEHOLDERS:
                blockers.append({"code": "local-launch-profile-placeholder", "field": field, "index": index, "placeholder": name})
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
    if value.get("allowPatterns") != []:
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
    _validate_argv_template(value.get("argvTemplate"), field="planningOnly.argvTemplate", placeholders=False, blockers=blockers, require_non_empty=True)
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


__all__ = [
    "ALLOWED_LAUNCH_PLACEHOLDERS",
    "LOCAL_HOST_LAUNCH_PROFILE_SCHEMA",
    "LOCAL_HOST_LAUNCH_PROFILE_VALIDATION_SCHEMA",
    "MAX_ARG_BYTES",
    "MAX_ARGV_ITEMS",
    "MAX_TIMEOUT_SECONDS",
    "PLANNING_ONLY_PROFILE_SCHEMA",
    "PLANNING_SUPPORT_STATUSES",
    "SAFE_VERSION_PROBES",
    "validate_local_launch_profile",
]
