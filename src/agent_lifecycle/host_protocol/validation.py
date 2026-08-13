"""Adapter descriptor and host-operation validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.thread_bridge_schemas import validate_thread_bridge_profile
from agent_lifecycle.host_protocol.acp_capability import validate_host_capabilities
from agent_lifecycle.host_protocol.contracts import HostOperationReceipt, HostOperationRequest
from agent_lifecycle.host_protocol.usage_normalizers import validate_usage_normalization_profile

REQUIRED_DESCRIPTOR_FIELDS = {
    "schemaVersion",
    "adapterId",
    "host",
    "maturity",
    "liveTestedHostRange",
    "contractCompatibility",
    "unsupportedOperationPolicy",
    "coreSemantics",
    "managedLaunch",
    "operations",
}
REQUIRED_OPERATION_NAMES = {
    "install",
    "discover",
    "validate-envelope",
    "launch",
    "model-route-execution",
    "wait",
    "cancel",
    "resume",
    "tool-execution",
    "adapter-event-stream",
    "result-collection",
    "usage-attestation",
    "task-audit",
    "final-audit",
}
INSTALLATION_FACTS_SCHEMA_VERSION = "agent-adapter-installation-facts.v1"
INSTALLATION_FILE_ACTIONS = {"read", "copy-preview"}
SHELL_EXECUTABLES = {"bash", "cmd", "powershell", "pwsh", "sh", "zsh"}


def validate_adapter_descriptor(
    descriptor: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    requests: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate one host adapter projection without executing host runtime code."""

    blockers: list[dict[str, Any]] = []
    _validate_descriptor_shape(descriptor, blockers)
    if baseline is not None:
        _validate_baseline(descriptor, baseline, blockers)
    request_contracts = [HostOperationRequest.from_json(item) for item in requests or []]
    receipt_contracts = [HostOperationReceipt.from_json(item) for item in receipts or []]
    _validate_request_receipt_pairs(request_contracts, receipt_contracts, blockers)
    status = "PASS" if not blockers else "FAIL"
    usage_validation = validate_usage_normalization_profile(
        descriptor.get("usageNormalization"),
        adapter_id=descriptor.get("adapterId") if isinstance(descriptor.get("adapterId"), str) else None,
        host=descriptor.get("host") if isinstance(descriptor.get("host"), str) else None,
    )
    return {
        "schemaVersion": "agent-host-adapter-validation.v1",
        "status": status,
        "adapterId": descriptor.get("adapterId"),
        "host": descriptor.get("host"),
        "maturity": descriptor.get("maturity"),
        "operationCount": len(descriptor.get("operations", [])) if isinstance(descriptor.get("operations"), list) else 0,
        "requestCount": len(request_contracts),
        "receiptCount": len(receipt_contracts),
        "usageNormalizationStatus": usage_validation["declaredStatus"],
        "blockers": blockers,
        "hostProtocolContracts": [
            HostOperationRequest.schema_version,
            HostOperationReceipt.schema_version,
        ],
    }


def _validate_descriptor_shape(descriptor: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if descriptor.get("schemaVersion") != "agent-lifecycle-host-adapter.v1":
        blockers.append({"code": "invalid-adapter-schema", "message": "unsupported adapter descriptor schemaVersion"})
    missing = sorted(field for field in REQUIRED_DESCRIPTOR_FIELDS if field not in descriptor)
    if missing:
        blockers.append({"code": "invalid-adapter-descriptor", "message": "required adapter descriptor fields are missing", "fields": missing})
    for key in ("adapterId", "host"):
        if not isinstance(descriptor.get(key), str) or not descriptor.get(key):
            blockers.append({"code": "invalid-adapter-descriptor", "message": f"{key} must be a non-empty string"})
    if descriptor.get("maturity") not in {"EXPERIMENTAL", "VERIFIED"}:
        blockers.append({"code": "invalid-adapter-maturity", "message": "adapter maturity must be EXPERIMENTAL or VERIFIED"})
    if descriptor.get("maturity") == "VERIFIED" and not descriptor.get("liveTestedHostRange"):
        blockers.append({"code": "verified-adapter-without-live-evidence", "message": "VERIFIED adapters require liveTestedHostRange evidence"})
    if descriptor.get("unsupportedOperationPolicy") != "fail-closed":
        blockers.append({"code": "adapter-unsupported-operation-policy", "message": "unsupported operations must fail closed"})
    if descriptor.get("coreSemantics") != "delegated-to-agent-lifecycle-core":
        blockers.append({"code": "adapter-core-semantics-overclaim", "message": "adapter must delegate lifecycle semantics to core"})
    _validate_managed_launch_profile(descriptor.get("managedLaunch"), blockers)
    if "threadBridge" in descriptor:
        thread_validation = validate_thread_bridge_profile(descriptor.get("threadBridge"))
        if thread_validation["status"] == "FAIL":
            blockers.append(
                {
                    "code": "adapter-thread-bridge-profile-invalid",
                    "message": "threadBridge profile failed validation",
                    "blockers": thread_validation["blockers"],
                }
            )
    usage_validation = validate_usage_normalization_profile(
        descriptor.get("usageNormalization"),
        adapter_id=descriptor.get("adapterId") if isinstance(descriptor.get("adapterId"), str) else None,
        host=descriptor.get("host") if isinstance(descriptor.get("host"), str) else None,
    )
    blockers.extend(usage_validation["blockers"])
    if "installation" in descriptor:
        _validate_installation_facts(descriptor.get("installation"), blockers)
    operations = descriptor.get("operations")
    if not isinstance(operations, list):
        blockers.append({"code": "invalid-adapter-operations", "message": "operations must be an array"})
        return
    provided = {item.get("name") for item in operations if isinstance(item, dict)}
    missing_operations = sorted(REQUIRED_OPERATION_NAMES.difference(provided))
    if missing_operations:
        blockers.append({"code": "adapter-required-operation-missing", "message": "required operations are missing", "operations": missing_operations})
    host_capabilities = descriptor.get("hostCapabilities")
    if host_capabilities is not None:
        validation = validate_host_capabilities(
            host_capabilities,
            adapter_id=descriptor.get("adapterId") if isinstance(descriptor.get("adapterId"), str) else None,
            host=descriptor.get("host") if isinstance(descriptor.get("host"), str) else None,
        )
        if validation["status"] == "FAIL":
            blockers.append(
                {
                    "code": "adapter-host-capability-invalid",
                    "message": "adapter hostCapabilities failed validation",
                    "blockers": validation["blockers"],
                }
            )


def validate_managed_launch_profile(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    _validate_managed_launch_profile(profile, blockers)
    return {
        "schemaVersion": "agent-managed-launch-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


def validate_local_host_launch_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate an operator-local profile through its single domain validator."""

    from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile

    return validate_local_launch_profile(profile)


def validate_installation_facts(facts: Any) -> dict[str, Any]:
    """Validate declarative adapter installation guidance without executing it."""

    blockers: list[dict[str, Any]] = []
    _validate_installation_facts(facts, blockers)
    return {
        "schemaVersion": "agent-adapter-installation-facts-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


def _validate_managed_launch_profile(profile: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(profile, dict):
        blockers.append({"code": "adapter-managed-launch-missing", "message": "managedLaunch must be an object"})
        return
    status = profile.get("status")
    if status not in {"SUPPORTED", "WRAPPER_ONLY", "UNSUPPORTED"}:
        blockers.append({"code": "adapter-managed-launch-status", "message": "managedLaunch status is invalid", "status": status})
    if profile.get("shell") is not False:
        blockers.append({"code": "adapter-managed-launch-shell", "message": "managedLaunch must declare shell false"})
    if profile.get("writesNativeConfig") is not False:
        blockers.append({"code": "adapter-managed-launch-native-config", "message": "managed launch must not write native host config"})
    if profile.get("promptInjectionDefault") is not False:
        blockers.append({"code": "adapter-managed-launch-prompt-injection", "message": "prompt injection must be disabled by default"})
    timeout = profile.get("timeoutSeconds")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        blockers.append({"code": "adapter-managed-launch-timeout", "message": "timeoutSeconds must be positive"})
    env = profile.get("env")
    if not isinstance(env, dict):
        blockers.append({"code": "adapter-managed-launch-env", "message": "managedLaunch env policy must be an object"})
    else:
        for key in ("allow", "allowPatterns"):
            value = env.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                blockers.append({"code": "adapter-managed-launch-env-list", "field": key})
        if env.get("projectPolicyAllowed") is not False and env.get("projectPolicyAllowed") is not True:
            blockers.append({"code": "adapter-managed-launch-env-project-policy", "message": "projectPolicyAllowed must be boolean"})
    if status == "SUPPORTED":
        templates = profile.get("argvTemplates")
        if not isinstance(templates, dict):
            blockers.append({"code": "adapter-managed-launch-argv", "message": "SUPPORTED managedLaunch requires argvTemplates"})
            return
        for mode in ("interactive", "managedTask", "resume"):
            argv = templates.get(mode)
            if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
                blockers.append({"code": "adapter-managed-launch-argv-template", "mode": mode})
    elif not isinstance(profile.get("reason"), str) or not profile.get("reason"):
        blockers.append({"code": "adapter-managed-launch-reason", "message": "non-supported managedLaunch profiles need a reason"})


def _validate_installation_facts(facts: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(facts, dict):
        blockers.append({"code": "adapter-installation-facts-missing", "message": "installation must be an object"})
        return
    if facts.get("schemaVersion") != INSTALLATION_FACTS_SCHEMA_VERSION:
        blockers.append(
            {
                "code": "adapter-installation-facts-schema",
                "message": "installation schemaVersion is invalid",
                "actual": facts.get("schemaVersion"),
            }
        )
    aliases = facts.get("binaryAliases")
    if not isinstance(aliases, list) or not aliases or not all(isinstance(item, str) and item.strip() == item for item in aliases):
        blockers.append({"code": "adapter-installation-binary-aliases", "message": "binaryAliases must be a non-empty string array"})
    elif len(set(aliases)) != len(aliases):
        blockers.append({"code": "adapter-installation-binary-aliases-duplicate", "message": "binaryAliases must be unique"})

    files = facts.get("files")
    if not isinstance(files, list) or not files:
        blockers.append({"code": "adapter-installation-files", "message": "installation files must be a non-empty array"})
    else:
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                blockers.append({"code": "adapter-installation-file", "index": index, "message": "file record must be an object"})
                continue
            path = item.get("path")
            if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or "\x00" in path:
                blockers.append({"code": "adapter-installation-file-path", "index": index})
            if item.get("action") not in INSTALLATION_FILE_ACTIONS:
                blockers.append({"code": "adapter-installation-file-action", "index": index})
            if not isinstance(item.get("required"), bool):
                blockers.append({"code": "adapter-installation-file-required", "index": index})

    commands = facts.get("commands")
    if not isinstance(commands, list) or not commands:
        blockers.append({"code": "adapter-installation-commands", "message": "installation commands must be a non-empty array"})
    else:
        for index, item in enumerate(commands):
            if not isinstance(item, dict):
                blockers.append({"code": "adapter-installation-command", "index": index, "message": "command record must be an object"})
                continue
            if "command" in item or "shell" in item:
                blockers.append({"code": "adapter-installation-command-shell", "index": index, "message": "commands must use argv arrays without shell fields"})
            argv = item.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value and "\n" not in value for value in argv):
                blockers.append({"code": "adapter-installation-command-argv", "index": index})
            elif argv[0].lower() in SHELL_EXECUTABLES:
                blockers.append({"code": "adapter-installation-command-shell", "index": index, "message": "shell executables are not installation guidance"})
            if not isinstance(item.get("purpose"), str) or not item["purpose"]:
                blockers.append({"code": "adapter-installation-command-purpose", "index": index})
            for field in ("mutatesHost", "requiresOperator"):
                if not isinstance(item.get(field), bool):
                    blockers.append({"code": "adapter-installation-command-flag", "index": index, "field": field})

    actions = facts.get("operatorActions")
    if not isinstance(actions, list) or not actions or not all(isinstance(item, str) and item for item in actions):
        blockers.append({"code": "adapter-installation-operator-actions", "message": "operatorActions must be a non-empty string array"})


def _validate_baseline(descriptor: dict[str, Any], baseline: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    rules = baseline.get("maturityRules", {})
    expected_maturity = rules.get("requiredReleaseMaturity")
    if expected_maturity and not _maturity_satisfies_baseline(descriptor, expected_maturity, rules):
        blockers.append({"code": "adapter-baseline-maturity-mismatch", "expected": expected_maturity, "actual": descriptor.get("maturity")})
    expected_policy = baseline.get("maturityRules", {}).get("unsupportedOperationPolicy")
    if expected_policy and descriptor.get("unsupportedOperationPolicy") != expected_policy:
        blockers.append({"code": "adapter-baseline-policy-mismatch", "expected": expected_policy, "actual": descriptor.get("unsupportedOperationPolicy")})
    expected_contract = baseline.get("contractCompatibility")
    if expected_contract and descriptor.get("contractCompatibility") != expected_contract:
        blockers.append({"code": "adapter-contract-compatibility-mismatch", "message": "descriptor contractCompatibility differs from baseline"})
    required = set(baseline.get("requiredOperations", []))
    if required:
        operations = descriptor.get("operations", [])
        provided = {item.get("name") for item in operations if isinstance(item, dict)}
        missing = sorted(required.difference(provided))
        if missing:
            blockers.append({"code": "adapter-baseline-operation-missing", "operations": missing})


def _maturity_satisfies_baseline(
    descriptor: dict[str, Any],
    expected_maturity: str,
    rules: dict[str, Any],
) -> bool:
    actual = descriptor.get("maturity")
    if actual == expected_maturity:
        return True
    return (
        expected_maturity == "EXPERIMENTAL"
        and actual == "VERIFIED"
        and rules.get("verifiedRequiresLiveEvidence") is True
        and bool(descriptor.get("liveTestedHostRange"))
    )


def _validate_request_receipt_pairs(
    requests: list[HostOperationRequest],
    receipts: list[HostOperationReceipt],
    blockers: list[dict[str, Any]],
) -> None:
    requests_by_operation = {item.operation_id: item for item in requests}
    for receipt in receipts:
        request = requests_by_operation.get(receipt.operation_id)
        if request is None:
            blockers.append({"code": "host-receipt-without-request", "operationId": receipt.operation_id})
            continue
        if request.capability != receipt.capability:
            blockers.append(
                {
                    "code": "host-receipt-capability-mismatch",
                    "operationId": receipt.operation_id,
                    "requestCapability": request.capability,
                    "receiptCapability": receipt.capability,
                }
            )


def require_adapter_validation_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("adapter-validation-failed", "adapter validation failed", {"validation": payload})
    return payload
