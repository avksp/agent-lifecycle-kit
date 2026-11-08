"""Compose local stage references with existing route and native launch guards."""

from __future__ import annotations

import hashlib
import stat
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent_lifecycle.accounting.source_usage_context import load_source_usage_context
from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.limited_native_evidence import native_success_event
from agent_lifecycle.adapter_sessions.local_launch_profile import (
    MAX_EXECUTABLE_IDENTITY_BYTES,
    build_executable_identity,
    load_local_launch_profile,
)
from agent_lifecycle.adapter_sessions.qualification import require_qualification_receipt, shipped_profile_digest
from agent_lifecycle.adapter_sessions.worktree_identity import capture_git_worktree_identity
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    load_json_object,
    read_json_object,
)
from agent_lifecycle.contracts.authority_io import create_authority_bytes, read_authority_bytes
from agent_lifecycle.contracts.quality_modes import mode_index, resolve_quality_floor
from agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity
from agent_lifecycle.model_routing.availability import project_availability
from agent_lifecycle.model_routing.resolver import resolve_model_route
from agent_lifecycle.model_routing.stage_bindings import (
    MAX_REGISTRY_BYTES,
    availability_probe_only,
    local_reference,
    neutral_stage_binding,
    ordered_stage_refs,
    portable_selection,
    select_stage,
    validate_stage_binding,
    validate_stage_registry,
)
from agent_lifecycle.policy.risk_execution import (
    derive_risk_execution_profile,
    resolve_risk_tier,
    validate_risk_execution_policy,
)
from agent_lifecycle.project.merge import build_effective_project_profile
from agent_lifecycle.project.profile import normalize_project_profile
from agent_lifecycle.resources import builtin_profile_path
from agent_lifecycle.workflow.state import require_current_authorization

_OFFICIAL_HOSTS = {
    "developers.openai.com",
    "platform.openai.com",
    "learn.chatgpt.com",
    "openai.com",
    "docs.anthropic.com",
    "code.claude.com",
    "opencode.ai",
}
_SENSITIVE_ENV = {
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
}


def read_local_object(root: Path, reference: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    local_reference(reference, model="modelClass" in reference)
    data = read_authority_bytes(root / reference["path"], root=root, max_bytes=MAX_REGISTRY_BYTES)
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise LifecycleError("stage-binding-reference-drift", "linked local input digest changed")
    return load_json_object(data, label="stage binding input"), data


def load_stage_registry(root: Path, profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    path = profile.get("policies", {}).get("executionBindings")
    reference = {"path": path, "sha256": "0" * 64}
    local_reference(reference)
    data = read_authority_bytes(root / path, root=root, max_bytes=MAX_REGISTRY_BYTES)
    registry = load_json_object(data, label="stage binding registry")
    validate_stage_registry(registry)
    return registry, {path: hashlib.sha256(data).hexdigest()}


def _auth_metadata(profile: dict[str, Any], root: Path) -> dict[str, Any]:
    """Observe link and target metadata; credential contents are never opened."""
    env, _ = resolve_launch_env(profile)
    home = env.get("CODEX_HOME") or str(Path(env.get("HOME", str(root))) / ".codex")
    path = Path(home) / "auth.json"
    link_revision = target_revision = None
    try:
        link = path.lstat()
        link_revision = [link.st_dev, link.st_ino, link.st_size, link.st_mtime_ns, link.st_ctime_ns]
        target = path.stat()
        if stat.S_ISREG(target.st_mode):
            target_revision = [target.st_dev, target.st_ino, target.st_size, target.st_mtime_ns, target.st_ctime_ns]
    except OSError:
        pass
    return {
        "homeDigest": canonical_digest(home),
        "authFileRevision": link_revision,
        "authTargetRevision": target_revision,
        "status": "PASS" if target_revision is not None else "UNAVAILABLE",
    }


def auth_revision_digest(profile: dict[str, Any], root: Path) -> str:
    return canonical_digest(_auth_metadata(profile, root))


def inspect_binding(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    host, _ = read_local_object(root, entry["hostModelProfile"])
    checked = validate_stage_binding(entry, host_profile=host)
    launch, _ = read_local_object(root, entry["launchProfile"])
    relative, loaded, validation = load_local_launch_profile(Path(entry["launchProfile"]["path"]), project_root=root)
    if loaded != launch or launch["adapterId"] != entry["adapterId"]:
        raise LifecycleError("stage-binding-launch-mismatch", "local launch adapter must match binding")
    evidence, _ = read_local_object(root, entry["parameterSupport"]["evidence"])
    source = urlsplit(str(evidence.get("source", "")))
    if source.scheme != "https" or source.hostname not in _OFFICIAL_HOSTS:
        raise LifecycleError(
            "stage-binding-parameter-evidence", "parameter support must reference official host documentation"
        )
    identity = build_executable_identity(
        launch,
        profile_digest=validation["profileDigest"],
        shipped_profile_digest=shipped_profile_digest(entry["adapterId"], repository_root=root),
        strict=False,
        max_executable_bytes=MAX_EXECUTABLE_IDENTITY_BYTES,
    )
    digest = checked["bindingDigest"]
    configuration = canonical_digest({"entry": entry, "launch": launch, "host": host})
    auth_metadata = _auth_metadata(launch, root)
    auth_digest = canonical_digest(auth_metadata)
    observation = None
    observation_path = root / ".alk/host-launch" / f"availability-{digest}.json"
    if observation_path.exists() or observation_path.is_symlink():
        observation = load_json_object(
            read_authority_bytes(observation_path, root=root, max_bytes=32768), label="binding observation"
        )
    availability = project_availability(
        configured=True,
        executable=identity,
        binding_digest=digest,
        configuration_digest=configuration,
        auth_revision_digest=auth_digest,
        observation=observation if auth_metadata["status"] == "PASS" else None,
        now=int(time.time()),
    )
    return {
        "entry": entry,
        "host": host,
        "launch": launch,
        "launchPath": relative,
        "launchValidation": validation,
        "identity": identity,
        "availability": availability,
        "authRevisionDigest": auth_digest,
        "authRevisionStatus": auth_metadata["status"],
        **checked,
    }


def require_binding_qualification(root: Path, inspected: dict[str, Any]) -> dict[str, Any]:
    entry, launch = inspected["entry"], inspected["launch"]
    policy = launch.get("qualification")
    if not isinstance(policy, dict):
        raise LifecycleError(
            "qualified-launch-policy-missing", "stage binding requires canonical version qualification"
        )
    expected_path = ".alk/host-launch/" + str(policy.get("receiptFile", ""))
    if entry["qualificationEvidence"]["path"] != expected_path:
        raise LifecycleError(
            "stage-binding-qualification-path", "qualification reference must be the exact launch policy receipt"
        )
    referenced, _ = read_local_object(root, entry["qualificationEvidence"])
    receipt = require_qualification_receipt(
        project_root=root,
        profile=launch,
        profile_digest=inspected["launchValidation"]["profileDigest"],
        executable_identity=inspected["identity"],
    )
    if receipt is None or referenced != receipt:
        raise LifecycleError("stage-binding-qualification-invalid", "canonical qualification receipt join failed")
    return receipt


def _codex_option_tokens(argv: list[str]) -> Iterator[tuple[int, str]]:
    """Inspect options without interpreting option values or a literal prompt."""
    value_options = {
        "--model",
        "-m",
        "--config",
        "-c",
        "--sandbox",
        "--cd",
        "-C",
        "--output-last-message",
        "-o",
        "--output-schema",
        "--color",
        "--image",
        "-i",
        "--add-dir",
        "--enable",
        "--disable",
        "--ask-for-approval",
        "-a",
    }
    skip = False
    for index, token in enumerate(argv[1:], 1):
        if skip:
            skip = False
            continue
        if token == "--":
            break
        yield index, token
        skip = token in value_options


def compose_codex_argv(argv: list[str], *, model: str, effort: str) -> list[str]:
    """Reuse exact canonical tokens, or inject each missing pair once."""
    output = list(argv)
    model_values: list[str] = []
    effort_values: list[str] = []
    for index, token in _codex_option_tokens(argv):
        if token in {"--model", "-m"}:
            if token != "--model" or index + 1 >= len(argv):
                raise LifecycleError("stage-binding-argv-conflict", "model requires canonical --model syntax")
            model_values.append(argv[index + 1])
        elif token.startswith(("--model=", "--profile", "--provider")) or token in {"-p", "--oss", "--local-provider"}:
            raise LifecycleError(
                "stage-binding-argv-conflict", "profile/provider/model overrides conflict with stage binding"
            )
        elif token in {"--config", "-c"}:
            if index + 1 >= len(argv):
                raise LifecycleError("stage-binding-argv-conflict", "config value is missing")
            value = argv[index + 1]
            key = value.split("=", 1)[0].strip()
            if key in {"model", "model_provider", "model_providers", "profile"} or key.startswith("model_providers."):
                raise LifecycleError("stage-binding-argv-conflict", "config overrides conflict with stage binding")
            if key == "model_reasoning_effort":
                if token != "--config":
                    raise LifecycleError("stage-binding-argv-conflict", "effort requires canonical --config syntax")
                effort_values.append(value)
        elif token.startswith(("--config=", "-c", "-m", "-p")):
            raise LifecycleError("stage-binding-argv-conflict", "combined parameter overrides are unsupported")
    expected_effort = f'model_reasoning_effort="{effort}"'
    if model_values not in ([], [model]) or effort_values not in ([], [expected_effort]):
        raise LifecycleError("stage-binding-argv-conflict", "duplicate or conflicting model/effort tokens")
    additions = ([] if model_values else ["--model", model]) + ([] if effort_values else ["--config", expected_effort])
    # Global Codex flags precede the subcommand and preserve the approved payload.
    return [output[0], *additions, *output[1:]]


def require_probe_working_directory(argv: list[str], root: Path) -> None:
    """Check option values against the actual trusted process working directory."""
    for index, token in _codex_option_tokens(argv):
        value = None
        if token in {"-C", "--cd"}:
            value = argv[index + 1] if index + 1 < len(argv) else ""
        elif token.startswith("--cd="):
            value = token[len("--cd=") :]
        elif token.startswith("-C"):
            value = token[2:]
        if value is not None:
            candidate = Path(value) if value else None
            if candidate is not None and not candidate.is_absolute():
                candidate = root / candidate
            if candidate is None or candidate.absolute() != root.absolute():
                raise LifecycleError(
                    "model-probe-containment-required", "diagnostic cwd must stay at the authorized project root"
                )


def _candidate_route(inspected: dict[str, Any], request: dict[str, Any], routing: dict[str, Any]) -> dict[str, Any]:
    route = resolve_model_route(request, routing, host_profile=inspected["host"])
    if route["modelClass"] not in {"no-model", inspected["modelClass"]}:
        raise LifecycleError("stage-binding-floor-refused", "binding does not satisfy the existing model resolver")
    return route


def select_stage_binding(
    *,
    root: Path,
    profile: dict[str, Any],
    profile_path: Path,
    mode: str,
    request: dict[str, Any],
    routing_profile: dict[str, Any],
    stage: str | None = None,
    binding_id: str | None = None,
    state: dict[str, Any] | None = None,
    explicit_probe: bool = False,
    task_id: str | None = None,
    probe_preparation: bool = False,
) -> dict[str, Any]:
    profile_raw = read_authority_bytes(profile_path, root=root, max_bytes=65536)
    current_profile = load_json_object(profile_raw, label="current project profile")
    supplied_normalized = normalize_project_profile(profile, project_root=root)
    current_normalized = normalize_project_profile(current_profile, project_root=root)
    if canonical_digest(supplied_normalized) != canonical_digest(current_normalized):
        raise LifecycleError(
            "stage-binding-project-profile-drift", "supplied project profile differs from current bytes"
        )
    profile = current_profile
    selected_stage = select_stage(mode, stage)
    if selected_stage in {"review", "audit", "finalization"}:
        request = {**request, "phase": "final-audit" if selected_stage == "finalization" else "independent-review"}
    if explicit_probe:
        task_id = _probe_operation_task_id(state, task_id, request)
    bound = _active_stage_binding(state, task_id)
    registry, pins = load_stage_registry(root, profile)
    refs = _approved_stage_refs(profile, registry, selected_stage, binding_id, bound)
    effective = build_effective_project_profile(profile, project_root=root)
    choice = _stage_candidate(
        root, registry, refs, request, routing_profile, selected_stage, explicit_probe or probe_preparation
    )
    if choice["status"] != "READY":
        return choice
    inspected, route = choice["inspected"], choice["route"]
    candidate, alternatives = choice["bindingId"], choice["alternatives"]
    for reference in (
        inspected["entry"]["hostModelProfile"],
        inspected["entry"]["launchProfile"],
        inspected["entry"]["qualificationEvidence"],
        inspected["entry"]["parameterSupport"]["evidence"],
    ):
        pins[reference["path"]] = reference["sha256"]
    profile_relative = profile_path.absolute().relative_to(root.absolute()).as_posix()
    pins[profile_relative] = hashlib.sha256(profile_raw).hexdigest()
    result = {
        "status": "READY",
        "visibility": "LOCAL_ONLY",
        "stage": selected_stage,
        "bindingId": candidate,
        "inspected": inspected,
        "pins": pins,
        "projectProfilePath": profile_relative,
        "projectProfileDigest": canonical_digest(profile),
        "effectiveProfileDigest": effective["effectiveProfileDigest"],
        "registryDigest": canonical_digest(registry),
        "modelClass": inspected["modelClass"],
        "selectedBindingDigest": inspected["bindingDigest"],
        "orderedBindingDigests": [canonical_digest(registry["bindings"][ref]) for ref in refs],
        "launchProfileDigest": inspected["launchValidation"]["profileDigest"],
        "executableDigest": inspected["identity"]["executableContentSha256"],
        "reasonCodes": ["EXPLICIT_PROBE" if explicit_probe else "APPROVED_STAGE_ORDER"],
        "winningSource": "command" if binding_id else "profile",
        "alternatives": alternatives,
        "explicitProbe": explicit_probe,
        "route": route,
    }
    registry_raw = read_authority_bytes(
        root / profile["policies"]["executionBindings"], root=root, max_bytes=MAX_REGISTRY_BYTES
    )
    result["neutralBinding"] = neutral_stage_binding(root, registry_raw, inspected["entry"], selected_stage)
    if bound is not None and bound != result["neutralBinding"]:
        raise LifecycleError(
            "stage-binding-active-attempt", "current binding configuration differs from the persisted attempt"
        )
    return result


def _probe_operation_task_id(state: dict[str, Any] | None, task_id: str | None, request: dict[str, Any]) -> str | None:
    if state is None or task_id is not None:
        return task_id
    matching = [
        row
        for row in state.get("tasks", [])
        if row.get("status") == "RUNNING"
        and row.get("attemptModelRoute", {}).get("operationId") == request.get("operationId")
    ]
    if len(matching) != 1:
        raise LifecycleError("stage-binding-active-attempt", "probe requires its unique adopted operation")
    return str(matching[0]["id"])


def _stage_candidate(
    root: Path,
    registry: dict[str, Any],
    refs: list[str],
    request: dict[str, Any],
    routing_profile: dict[str, Any],
    selected_stage: str,
    availability_exception: bool,
) -> dict[str, Any]:
    alternatives = []
    inspected = None
    route = None
    for candidate in refs:
        entry = registry["bindings"][candidate]
        current = inspect_binding(root, entry)
        route = _candidate_route(current, request, routing_profile)
        if route["modelClass"] == "no-model":
            return {
                "status": "NO_MODEL",
                "stage": selected_stage,
                "modelClass": "no-model",
                "reasonCodes": route["reasonCodes"],
            }
        if current["identity"]["status"] != "PASS":
            alternatives.append({"bindingDigest": current["bindingDigest"], "reason": "EXECUTABLE_UNAVAILABLE"})
            continue
        require_binding_qualification(root, current)
        if not availability_exception and current["availability"]["status"] != "PASS":
            return {
                "status": "BLOCKED",
                "stage": selected_stage,
                "reasonCodes": ["BINDING_AVAILABILITY_UNKNOWN"],
                "alternatives": alternatives,
                "preparation": "Explicitly authorize model availability --probe for the selected binding",
            }
        inspected = current
        break
    if inspected is None:
        return {
            "status": "BLOCKED",
            "stage": selected_stage,
            "reasonCodes": ["APPROVED_BINDINGS_EXHAUSTED"],
            "alternatives": alternatives,
        }
    return {
        "status": "READY",
        "inspected": inspected,
        "route": route,
        "bindingId": candidate,
        "alternatives": alternatives,
    }


def _active_stage_binding(state: dict[str, Any] | None, task_id: str | None) -> dict[str, Any] | None:
    active = [
        task
        for task in (state or {}).get("tasks", [])
        if task.get("status") in {"RUNNING", "VALIDATING", "VERIFYING"}
        and (task_id is None or task.get("id") == task_id)
    ]
    bound = active[0].get("attemptExecutionStrategy", {}).get("stageBinding") if active else None
    if active and bound is None:
        raise LifecycleError(
            "stage-binding-active-attempt",
            "active unbound attempt requires canonical recovery; prepare and adopt before a new attempt",
            {"preparation": "start --strategy-out then workflow task-start --strategy"},
        )
    return bound


def _approved_stage_refs(
    profile: dict[str, Any], registry: dict[str, Any], stage: str, binding_id: str | None, bound: dict[str, Any] | None
) -> list[str]:
    refs = ordered_stage_refs(profile, stage, binding_id)
    if bound is not None:
        refs = [
            ref for ref in refs if canonical_digest(registry["bindings"].get(ref)) == bound.get("selectedBindingDigest")
        ]
        if len(refs) != 1 or bound.get("stage") != stage:
            raise LifecycleError(
                "stage-binding-active-attempt",
                "active attempt can consume only its persisted binding; no late fallback",
            )
    if set(refs) - set(registry["bindings"]):
        raise LifecycleError("stage-binding-missing", "stage references absent registry entries")
    return refs


def seal_stage_launch(
    selection: dict[str, Any], *, state_path: Path, task_id: str, source_revision: str
) -> dict[str, Any]:
    state = read_json_object(state_path, label="current workflow state")
    task: dict[str, Any] = next((item for item in state.get("tasks", []) if item.get("id") == task_id), {})
    return {
        **selection,
        "sourceRevision": source_revision,
        "statePath": str(state_path),
        "taskId": task_id,
        "operationId": task.get("attemptModelRoute", {}).get("operationId"),
        "expectedRevision": state.get("stateRevision"),
        "expectedAttempt": task.get("attempt"),
        "deadline": task.get("attemptDeadlineAt"),
    }


def guarded_stage_context(
    context: Any,
    selection: dict[str, Any],
    *,
    operation: str,
    route_id: str | None,
    requested_claim: str | None,
    input_request: Path | None,
) -> Any:
    if operation != "managedTask" or any(value is not None for value in (route_id, requested_claim, input_request)):
        raise LifecycleError(
            "stage-binding-special-route-refused", "stage opt-in is qualified only on the ordinary managed route"
        )
    inspected = selection["inspected"]
    if inspected["entry"]["adapterId"] != "codex" or context.profile_digest != selection["launchProfileDigest"]:
        raise LifecycleError("stage-binding-route-not-qualified", "selected native route is not qualified")
    model = inspected["host"]["bindings"][selection["modelClass"]]["providerModel"]
    effort = inspected["entry"]["hostParameters"]["reasoningEffort"]
    compose_codex_argv(
        [str(context.profile["executable"]), *context.profile["argvTemplate"]], model=model, effort=effort
    )
    original = context.runner
    used = False

    def guarded_runner(argv: list[str], **kwargs: Any) -> dict[str, Any]:
        nonlocal used
        if used:
            raise LifecycleError("stage-binding-no-retry", "one immutable dispatch was already attempted")
        try:
            verify_stage_sink(context, selection)
            actual = compose_codex_argv(argv, model=model, effort=effort)
            if selection["explicitProbe"]:
                require_probe_working_directory(actual, context.root)
            from agent_lifecycle.adapter_sessions.managed_process import _original_attempt_deadline

            state = read_json_object(Path(selection["statePath"]), label="workflow state")
            task = next(item for item in state["tasks"] if item["id"] == selection["taskId"])
            kwargs["absolute_deadline_monotonic_ns"] = _original_attempt_deadline(state, task)
            selection["invocationDigest"] = canonical_digest(actual)
            dispatch_observation = _claim_dispatch_observation(context, selection, state, task)
        except (LifecycleError, OSError) as error:
            return {
                "status": "BLOCKED",
                "processStarted": False,
                "blockers": [
                    {"code": error.code if isinstance(error, LifecycleError) else "stage-binding-sink-unavailable"}
                ],
            }
        selection["invocationDigest"] = canonical_digest(actual)
        selection["localInvocation"] = {
            "argv": actual,
            "requestedModel": model,
            "configuredModel": model,
            "requestedEffort": effort,
            "configuredEffort": effort,
            "reportedModelIdentity": "UNAVAILABLE",
            "effortAttestation": "UNAVAILABLE",
            "backendIdentityAttestation": "UNAVAILABLE",
        }
        used = True
        kwargs["cwd"] = context.root
        kwargs["max_output_bytes"] = selection.get("maxOutputBytes", 65536)
        kwargs["timeout_seconds"] = min(kwargs["timeout_seconds"], selection.get("maxWallSeconds", 300))
        kwargs["env"] = {
            key: value
            for key, value in kwargs["env"].items()
            if key not in _SENSITIVE_ENV and not key.startswith(("OPENAI_", "AZURE_OPENAI_"))
        }
        result = original(actual, **kwargs)
        selection["localProcessResult"] = result
        _record_dispatch_disposition(context, dispatch_observation, result)
        return result

    return replace(context, runner=guarded_runner)


def _claim_dispatch_observation(
    context: Any, selection: dict[str, Any], state: dict[str, Any], task: dict[str, Any]
) -> Path | None:
    """An observation can refuse a duplicate; it grants no launch authority."""
    if selection["explicitProbe"]:
        return None  # The explicit probe already has its immutable experiment observation.
    lineage = {"runId": state.get("runId"), "taskId": selection["taskId"], "attempt": task.get("attempt")}
    path = context.root / ".alk/host-launch" / ("dispatch-" + canonical_digest(lineage) + ".json")
    observation = {
        "schemaVersion": "agent-local-dispatch-observation.v1",
        "disposition": "PENDING",
        "lineage": lineage,
        "operationId": selection.get("operationId"),
        "sourceRevision": selection["sourceRevision"],
        "stageBinding": selection["neutralBinding"],
        "invocationDigest": selection["invocationDigest"],
        "originalDeadline": selection["deadline"],
        "authorityClaimed": False,
        "retryAuthorized": False,
    }
    try:
        create_authority_bytes(path, canonical_bytes(observation) + b"\n", root=context.root, private=True)
    except FileExistsError:
        raise LifecycleError(
            "stage-binding-dispatch-reconcile",
            "this native attempt already has a dispatch observation; reconcile it or use canonical recovery",
        ) from None
    return path


def _record_dispatch_disposition(context: Any, path: Path | None, result: dict[str, Any]) -> None:
    if (
        path is None
        or type(result.get("processStarted")) is not bool
        or result.get("timedOut")
        or result.get("cancelled")
    ):
        return
    if result["processStarted"] is False:
        if result.get("status") == "PASS" or result.get("startedFailure") or result.get("processReceipt") is not None:
            return
        disposition = "PROVEN_NO_START"
    elif result.get("status") == "PASS":
        disposition = "SUCCEEDED"
    elif type(result.get("exitCode")) is int:
        disposition = "TERMINAL_FAILURE"
    else:
        return
    terminal = {
        "schemaVersion": "agent-local-dispatch-disposition.v1",
        "disposition": disposition,
        "processResultDigest": canonical_digest(result),
        "authorityClaimed": False,
        "retryAuthorized": False,
    }
    create_authority_bytes(
        path.with_name(path.stem + "-result.json"), canonical_bytes(terminal) + b"\n", root=context.root, private=True
    )


def verify_stage_sink(context: Any, selection: dict[str, Any]) -> None:
    for path, digest in selection["pins"].items():
        data = read_authority_bytes(context.root / path, root=context.root, max_bytes=65536)
        if hashlib.sha256(data).hexdigest() != digest:
            raise LifecycleError("stage-binding-input-drift", "stage binding input changed before native dispatch")
    state = read_json_object(Path(selection["statePath"]), label="workflow state")
    require_current_authorization(state)
    task: dict[str, Any] = next((item for item in state.get("tasks", []) if item.get("id") == selection["taskId"]), {})
    if (
        state.get("sourceRevision") != selection["sourceRevision"]
        or state.get("stateRevision") != selection["expectedRevision"]
        or task.get("attempt") != selection["expectedAttempt"]
        or task.get("attemptDeadlineAt") != selection["deadline"]
        or task.get("status") != "RUNNING"
    ):
        raise LifecycleError("stage-binding-native-lineage-drift", "current native task lineage changed")
    if task.get("attemptExecutionStrategy", {}).get("stageBinding") != selection["neutralBinding"]:
        raise LifecycleError("stage-binding-active-attempt", "native sink requires the same persisted binding identity")
    manifest_path = context.root / state["manifestPath"]
    manifest = read_json_object(manifest_path, label="actual frozen manifest")
    lock = read_json_object(manifest_path.with_name("plan.lock.json"), label="actual frozen lock")
    verify_plan_package_integrity(manifest, lock, repository_root=context.root)
    if canonical_digest(manifest) != state.get("planDigest"):
        raise LifecycleError("stage-binding-native-lineage-drift", "actual frozen purpose lineage changed")
    if availability_probe_only(manifest, task["id"]) and not selection["explicitProbe"]:
        raise LifecycleError("stage-binding-probe-only", "probe-only task cannot dispatch ordinary managed work")
    route = task.get("attemptModelRoute", {})
    if route.get("operationId") != selection.get("operationId", route.get("operationId")):
        raise LifecycleError("stage-binding-active-attempt", "probe operation differs from adopted attempt")
    _reopen_stage_policies(context.root, selection)
    if capture_git_worktree_identity(context.root)["head"] != selection["sourceRevision"]:
        raise LifecycleError("stage-binding-source-drift", "actual repository source revision changed")
    current = inspect_binding(context.root, selection["inspected"]["entry"])
    if (
        current["identity"] != selection["inspected"]["identity"]
        or current["authRevisionDigest"] != selection["inspected"]["authRevisionDigest"]
    ):
        raise LifecycleError("stage-binding-executable-drift", "executable or auth revision changed")
    require_binding_qualification(context.root, current)
    if not selection["explicitProbe"] and current["availability"]["status"] != "PASS":
        raise LifecycleError("stage-binding-observation-expired", "ordinary selection requires fresh availability")
    caps, totals = state.get("budgets", {}), task.get("usageTotals", {})
    if totals.get("toolCalls", 0) >= caps.get("maxToolCallsPerTask", 0):
        raise LifecycleError("stage-binding-admission-exhausted", "original task admission is exhausted")


def stage_launch_receipt(receipt: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    body.update(
        stageBinding=portable_selection(selection),
        modelResponse=observe_codex_model_response(selection.get("localProcessResult")),
        argv=["<local-stage-invocation>"],
        stdout={"tail": "", "redacted": True},
        stderr={"tail": "", "redacted": True},
    )
    body["modelCallsStarted"] = receipt.get("hostLaunchStarted", False)
    return {**body, "receiptDigest": canonical_digest(body)}


def observe_codex_model_response(process: dict[str, Any] | None) -> dict[str, Any]:
    """Observe a bounded complete model response, without attesting its identity."""
    unavailable = {"status": "UNAVAILABLE", "backendIdentityAttested": False}
    result = process or {}
    stdout = result.get("stdout")
    if not isinstance(stdout, str) or any(
        result.get(key) for key in ("timedOut", "cancelled", "outputLimitExceeded", "stdoutRedacted")
    ):
        return unavailable
    try:
        if len(stdout.encode("utf-8")) > 65536:
            return unavailable
        terminal = native_success_event({**result, "stdoutTail": stdout})
        events: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            if line.strip():
                event = load_json_object(line.encode("utf-8"), label="native model response event")
                canonical_bytes(event)
                events.append(event)
    except (LifecycleError, ValueError, UnicodeError):
        return unavailable
    if not events or any(not isinstance(event, dict) for event in events) or events[-1] != terminal:
        return unavailable
    messages = [
        event["item"]["text"]
        for event in events[:-1]
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
        and event["item"]["text"].strip()
    ]
    if not messages:
        return unavailable
    return {
        "status": "PASS",
        "responseDigest": canonical_digest(messages),
        "lastResponseDigest": canonical_digest(messages[-1].strip()),
        "responseCount": len(messages),
        "terminalDigest": canonical_digest(terminal),
        "backendIdentityAttested": False,
    }


def portable_stage_start(receipt: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    """Remove local stage IDs from nested guided and session projections."""

    def project(value: Any) -> Any:
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value
        body = {
            key: project(item)
            for key, item in value.items()
            if key not in {"receiptDigest", "executionBindingRefs", "executionBindings"}
        }
        if "executionBindingRefs" in value:
            body["executionBindingRefsDigest"] = canonical_digest(value["executionBindingRefs"])
        if "receiptDigest" in value:
            if body.get("hostLaunchStarted") is True and "modelCallsStarted" in body:
                body["modelCallsStarted"] = True
            body["receiptDigest"] = canonical_digest(body)
        return body

    result = project(receipt)
    result.pop("receiptDigest", None)
    result["stageBinding"] = portable_selection(selection)
    result["receiptDigest"] = canonical_digest(result)
    return result


def derive_binding_risk(
    selection: dict[str, Any],
    *,
    root: Path,
    state_path: Path,
    manifest_path: Path,
    task_id: str,
    operation_id: str,
    source_revision: str,
) -> dict[str, Any]:
    state = read_json_object(state_path, label="workflow state")
    policies = _reopen_stage_policies(root, selection)
    selection["policyContext"] = policies
    selection["pins"].update(policies["pins"])
    manifest = read_json_object(manifest_path, label="manifest")
    task: dict[str, Any] = next((row for row in state["tasks"] if row["id"] == task_id), {})
    adapter_id = selection["inspected"]["entry"]["adapterId"]
    host = selection["inspected"]["host"]["host"]
    return derive_risk_execution_profile(
        manifest=manifest,
        state=state,
        task_id=task_id,
        adapter_id=selection["inspected"]["entry"]["adapterId"],
        adapter_host=selection["inspected"]["host"]["host"],
        operation_id=operation_id,
        source_revision=source_revision,
        requested_risk=policies["requestedRisk"],
        risk_policy=policies["riskPolicy"],
        routing_profile=policies["routingProfile"],
        baseline_profile=policies["baselineProfile"],
        host_profile=selection["inspected"]["host"],
        repository_root=root,
        source_usage_context=load_source_usage_context(root, manifest, state, task, adapter_id, host),
    )


def stage_policy_inputs(root: Path, profile: dict[str, Any], *, stage: str = "implementation") -> dict[str, Any]:
    """Use validated project references and existing bounded root-safe readers."""
    effective = build_effective_project_profile(profile, project_root=root)
    defaults = {
        "routingProfile": "model-routing-profile.v1.json",
        "riskPolicy": "risk-execution-policy.v1.json",
        "baselineProfile": "lifecycle-baselines.v1.json",
    }
    # Generated S0 display defaults must not replace an explicit auto request.
    stage_risk = profile.get("stages", {}).get(stage, {}).get("risk", profile.get("defaultRisk", "auto"))
    result: dict[str, Any] = {"pins": {}, "digests": {}, "requestedRisk": stage_risk}
    for name, default in defaults.items():
        reference = effective["policies"].get(name)
        path = root / reference if reference else Path(builtin_profile_path(default))
        raw = read_authority_bytes(path, root=root if reference else None, max_bytes=65536)
        result[name] = load_json_object(raw, label=name)
        result["digests"][name] = hashlib.sha256(raw).hexdigest()
        if reference:
            result["pins"][reference] = result["digests"][name]
    if validate_risk_execution_policy(result["riskPolicy"])["status"] != "PASS":
        raise LifecycleError("stage-binding-risk-policy-invalid", "current project risk policy is invalid")
    return result


def stage_policy_request(request: dict[str, Any], policies: dict[str, Any]) -> dict[str, Any]:
    supplied_tier = request.get("sddTier")
    if not isinstance(supplied_tier, str):
        raise LifecycleError("invalid-model-route-request", "sddTier must be a current supplied tier")
    tier = resolve_risk_tier(supplied_tier, policies["requestedRisk"])
    quality = resolve_quality_floor(
        task_shape=str(request.get("taskShape", "feature")),
        baseline_profile=policies["baselineProfile"],
        sdd_tier=tier,
        risk_flags=request.get("riskFlags", {}),
    )
    if quality["status"] != "PASS":
        raise LifecycleError(
            "stage-binding-quality-floor-refused", "project baseline cannot resolve the current quality floor"
        )
    floor = quality["qualityFloor"]
    previous = request.get("qualityFloor")
    if previous is not None and mode_index(previous) > mode_index(floor):
        floor = previous
    result = {**request, "sddTier": tier, "qualityFloor": floor}
    result.setdefault("budgetClass", policies["riskPolicy"]["tiers"][tier]["budgetClass"])
    return result


def _reopen_stage_policies(root: Path, selection: dict[str, Any]) -> dict[str, Any]:
    profile = load_json_object(
        read_authority_bytes(root / selection["projectProfilePath"], root=root, max_bytes=65536),
        label="current project profile",
    )
    current = stage_policy_inputs(root, profile, stage=selection["stage"])
    previous = selection.get("policyContext")
    if previous is not None and (
        previous["digests"] != current["digests"] or previous["requestedRisk"] != current["requestedRisk"]
    ):
        raise LifecycleError(
            "stage-binding-policy-drift", "current project policy bytes changed before native dispatch"
        )
    return current
