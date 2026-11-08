"""Project-local setup, explanation and explicitly authorized native probes."""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions import stage_launch
from agent_lifecycle.adapter_sessions.launcher import launch_from_local_profile
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    load_json_object,
    normalize_repo_path,
    read_json_object,
)
from agent_lifecycle.contracts.authority_io import create_authority_bytes, read_authority_bytes, replace_authority_bytes
from agent_lifecycle.contracts.process_lock import exclusive_process_lock
from agent_lifecycle.model_routing.availability import build_probe_observation
from agent_lifecycle.model_routing.setup import setup_proposal
from agent_lifecycle.model_routing.stage_bindings import portable_selection
from agent_lifecycle.project.profile import validate_project_profile
from agent_lifecycle.workflow.state import require_current_authorization


def add_model_setup_parsers(subparsers: Any) -> None:
    setup = subparsers.add_parser("setup", help="discover or prepare project-local stage bindings")
    mode = setup.add_mutually_exclusive_group(required=True)
    mode.add_argument("--discover", action="store_true")
    mode.add_argument("--manual", action="store_true")
    setup.add_argument("--input")
    setup.add_argument("--scope", choices=["project"], default="project")
    setup.add_argument("--project-profile", default=".alk/project-profile.json")
    setup.add_argument("--apply", action="store_true")
    setup.add_argument("--expected-profile-digest")
    setup.add_argument("--portable", action="store_true")
    explain = subparsers.add_parser("explain", help="explain ordered stage eligibility without launching")
    explain.add_argument(
        "--stage",
        required=True,
        choices=["intake", "research", "planning", "review", "implementation", "audit", "finalization"],
    )
    explain.add_argument("--project-profile", required=True)
    explain.add_argument("--request", required=True)
    explain.add_argument("--portable", action="store_true")
    availability = subparsers.add_parser(
        "availability", help="check local binding observations; live probe requires current native authority"
    )
    availability.add_argument("--binding", required=True)
    availability.add_argument("--project-profile", required=True)
    availability.add_argument("--portable", action="store_true")
    availability.add_argument("--probe", action="store_true")
    for name in ("authorization-receipt", "state", "manifest", "lock", "task", "operation-id", "source-revision"):
        availability.add_argument("--" + name)
    for name in ("expected-revision", "max-invocations", "max-wall-seconds", "max-output-bytes"):
        availability.add_argument("--" + name, type=int)


def dispatch_model_setup(args: Any) -> dict[str, Any]:
    root = Path.cwd().absolute()
    if args.model_command == "setup":
        return _setup(args, root)
    profile_path = _project_path(root, args.project_profile)
    profile = _read_profile(root, profile_path)
    if args.model_command == "explain":
        request = read_json_object(Path(args.request), label="model route request")
        policies = stage_launch.stage_policy_inputs(root, profile, stage=args.stage)
        request = stage_launch.stage_policy_request(request, policies)
        mode = {
            "intake": "auto",
            "planning": "plan",
            "implementation": "implement",
            "audit": "review",
            "finalization": "review",
        }.get(args.stage, args.stage)
        selection = stage_launch.select_stage_binding(
            root=root,
            profile=profile,
            profile_path=profile_path,
            mode=mode,
            stage=args.stage,
            request=request,
            routing_profile=policies["routingProfile"],
        )
        return _explain_view(selection, portable=args.portable)
    registry, _ = stage_launch.load_stage_registry(root, profile)
    if args.binding not in registry["bindings"]:
        raise LifecycleError("stage-binding-missing", "requested binding is absent")
    inspected = stage_launch.inspect_binding(root, registry["bindings"][args.binding])
    if args.probe:
        return _probe(args, root, profile, profile_path, inspected)
    result = {**inspected["availability"], "visibility": "PORTABLE" if args.portable else "LOCAL_ONLY"}
    if not args.portable:
        entry = inspected["entry"]
        result.update(
            bindingId=args.binding,
            adapterId=entry["adapterId"],
            model=inspected["host"]["bindings"][inspected["modelClass"]]["providerModel"],
            reasoningEffort=entry["hostParameters"]["reasoningEffort"],
        )
    return result


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    relative = (
        path.absolute().relative_to(root).as_posix()
        if path.is_absolute()
        else normalize_repo_path(value, label="project profile")
    )
    if not relative.startswith(".alk/"):
        raise LifecycleError("model-setup-profile-path", "setup project profile must remain below .alk")
    # Existing safe readers/writers reject every symlink component.
    return root / relative


def _read_profile(root: Path, path: Path) -> dict[str, Any]:
    profile = load_json_object(read_authority_bytes(path, root=root, max_bytes=65536), label="project profile")
    validate_project_profile(profile, project_root=root)
    return profile


def _setup(args: Any, root: Path) -> dict[str, Any]:
    discovery = discover_local_tools() if args.discover else None
    payload = (
        load_json_object(read_authority_bytes(Path(args.input).absolute(), max_bytes=98304), label="manual setup input")
        if args.input
        else None
    )
    proposal = setup_proposal(payload)
    if payload is not None:
        validate_project_profile(payload["projectProfile"], project_root=root)
        for entry in payload["registry"]["bindings"].values():
            stage_launch.inspect_binding(root, entry)
            stage_launch.read_local_object(root, entry["qualificationEvidence"])
    if discovery is not None:
        proposal["discovery"] = discovery
    if args.apply:
        if payload is None:
            return proposal
        if not args.expected_profile_digest:
            raise LifecycleError("model-setup-cas-required", "--apply requires --expected-profile-digest or ABSENT")
        proposal = apply_setup(root, _project_path(root, args.project_profile), proposal, args.expected_profile_digest)
    if args.portable:
        return {
            key: proposal[key]
            for key in (
                "schemaVersion",
                "status",
                "scope",
                "proposalDigest",
                "registryDigest",
                "bindingCount",
                "modelCallsStarted",
                "applied",
                "requiredFields",
                "qualificationStatus",
            )
            if key in proposal
        }
    return proposal


def apply_setup(root: Path, path: Path, proposal: dict[str, Any], expected_digest: str) -> dict[str, Any]:
    registry_bytes = canonical_bytes(proposal["registry"]) + b"\n"
    registry_hash = hashlib.sha256(registry_bytes).hexdigest()
    registry_path = ".alk/host-launch/stage-bindings-" + registry_hash + ".json"
    profile = copy.deepcopy(proposal["projectProfile"])
    profile.setdefault("policies", {})["executionBindings"] = registry_path
    validate_project_profile(profile, project_root=root)
    data = canonical_bytes(profile) + b"\n"
    if len(registry_bytes) > 32768 or len(data) > 65536:
        raise LifecycleError("model-setup-limit", "setup output exceeds its byte bound")
    with exclusive_process_lock(path.with_name(path.name + ".setup.lock"), timeout_seconds=1):
        try:
            before = read_authority_bytes(path, root=root, max_bytes=65536)
        except FileNotFoundError:
            before = None
        actual = "ABSENT" if before is None else hashlib.sha256(before).hexdigest()
        if actual != expected_digest:
            raise LifecycleError("model-setup-profile-drift", "current project profile does not match expected digest")
        target = root / registry_path
        try:
            create_authority_bytes(target, registry_bytes, root=root, private=True)
        except FileExistsError:
            if read_authority_bytes(target, root=root, max_bytes=32768) != registry_bytes:
                raise LifecycleError("model-setup-registry-collision", "immutable registry bytes differ") from None
        try:
            current = read_authority_bytes(path, root=root, max_bytes=65536)
        except FileNotFoundError:
            current = None
        if current != before:
            raise LifecycleError("model-setup-profile-drift", "project profile changed before pointer commit")
        if before is None:
            create_authority_bytes(path, data, root=root, private=True)
        else:
            replace_authority_bytes(path, data, root=root)
    return {**proposal, "projectProfile": profile, "applied": True, "profileDigest": hashlib.sha256(data).hexdigest()}


def discover_local_tools() -> dict[str, Any]:
    """Only known CLI version/help argv, with bounded capture and no config crawl."""
    started = time.monotonic()
    observations = []
    processes = 0
    for adapter in ("codex", "claude", "opencode"):
        executable = shutil.which(adapter)
        item: dict[str, Any] = {
            "adapterId": adapter,
            "discovered": executable is not None,
            "modelListStatus": "MODEL_LIST_UNAVAILABLE",
            "authObservation": "UNAVAILABLE",
            "probeObservation": "UNAVAILABLE",
            "qualityQualification": "UNAVAILABLE",
        }
        if executable is not None:
            for flags in (["--version"], ["--help"]):
                if processes >= 12 or time.monotonic() - started >= 60:
                    break
                result = run_process(
                    [executable, *flags],
                    env={name: os.environ[name] for name in ("HOME", "PATH", "SYSTEMROOT") if name in os.environ},
                    timeout_seconds=min(5, 60 - (time.monotonic() - started)),
                    max_output_bytes=65536,
                )
                processes += 1
                item["version" if flags == ["--version"] else "help"] = {
                    "status": result.get("status"),
                    "outputDigest": canonical_digest([result.get("stdoutTail"), result.get("stderrTail")]),
                }
        observations.append(item)
    return {
        "observations": observations,
        "processCalls": processes,
        "modelCallsStarted": False,
        "visibility": "LOCAL_ONLY",
    }


def _explain_view(selection: dict[str, Any], *, portable: bool) -> dict[str, Any]:
    result = {
        "schemaVersion": "agent-stage-binding-explanation.v1",
        **portable_selection(selection),
        "alternatives": selection.get("alternatives", []),
        "modelCallsStarted": False,
        "visibility": "PORTABLE" if portable else "LOCAL_ONLY",
    }
    inspected = selection.get("inspected")
    if inspected is not None:
        result.update(route=selection["route"], availability=inspected["availability"])
        if not portable:
            result.update(
                bindingId=selection["bindingId"],
                adapterId=inspected["entry"]["adapterId"],
                model=inspected["host"]["bindings"][selection["modelClass"]]["providerModel"],
                reasoningEffort=inspected["entry"]["hostParameters"]["reasoningEffort"],
            )
    return result


def _probe(
    args: Any, root: Path, profile: dict[str, Any], profile_path: Path, inspected: dict[str, Any]
) -> dict[str, Any]:
    required = (
        "authorization_receipt",
        "state",
        "manifest",
        "lock",
        "task",
        "operation_id",
        "expected_revision",
        "source_revision",
        "max_invocations",
        "max_wall_seconds",
        "max_output_bytes",
    )
    if any(getattr(args, name) is None for name in required):
        raise LifecycleError(
            "model-probe-missing-input",
            "explicit probe requires current native bindings and finite caps",
            {"requiredFields": list(required)},
        )
    if args.max_invocations != 1 or not 1 <= args.max_wall_seconds <= 300 or not 1 <= args.max_output_bytes <= 65536:
        raise LifecycleError(
            "model-probe-cap-invalid", "probe requires one CLI dispatch with at most 300 seconds and 65536 bytes"
        )
    state_path = Path(args.state).absolute()
    state = read_json_object(state_path, label="workflow state")
    require_current_authorization(state)
    if state.get("stateRevision") != args.expected_revision or state.get("sourceRevision") != args.source_revision:
        raise LifecycleError("model-probe-lineage-mismatch", "probe state revision/source changed")
    authority = state["authorization"].get("authorizationReceipt", {})
    auth_path = Path(args.authorization_receipt).absolute()
    raw = read_authority_bytes(auth_path, root=root, max_bytes=32768)
    authorization_receipt = load_json_object(raw, label="consumed native authorization receipt")
    if (
        authority.get("path") != auth_path.relative_to(root).as_posix()
        or authority.get("sha256") != canonical_digest(authorization_receipt)
        or authority.get("bytes") != len(canonical_bytes(authorization_receipt) + b"\n")
    ):
        raise LifecycleError(
            "model-probe-authorization-mismatch", "probe must use the actual consumed native authorization receipt"
        )
    task: dict[str, Any] = next((item for item in state.get("tasks", []) if item.get("id") == args.task), {})
    if task.get("status") != "RUNNING":
        raise LifecycleError("model-probe-task-not-running", "probe requires its current running authorized task")
    manifest = read_json_object(Path(args.manifest), label="manifest")
    _require_probe_containment(inspected["launch"]["argvTemplate"], root)
    request = _probe_route_request(args, manifest)
    policies = stage_launch.stage_policy_inputs(root, profile)
    request = stage_launch.stage_policy_request(request, policies)
    selection = stage_launch.select_stage_binding(
        root=root,
        profile=profile,
        profile_path=profile_path,
        mode="implement",
        binding_id=args.binding,
        request=request,
        routing_profile=policies["routingProfile"],
        state=state,
        explicit_probe=True,
    )
    if selection.get("status") != "READY":
        return _explain_view(selection, portable=args.portable)
    selection["policyContext"] = policies
    selection["pins"].update(policies["pins"])
    selection = stage_launch.seal_stage_launch(
        selection, state_path=state_path, task_id=args.task, source_revision=args.source_revision
    )
    selection.update(maxWallSeconds=args.max_wall_seconds, maxOutputBytes=args.max_output_bytes)
    risk = stage_launch.derive_binding_risk(
        selection,
        root=root,
        state_path=state_path,
        manifest_path=Path(args.manifest),
        task_id=args.task,
        operation_id=args.operation_id,
        source_revision=args.source_revision,
    )
    if risk["modelRoute"]["modelClass"] != selection["modelClass"]:
        raise LifecycleError("stage-binding-floor-refused", "probe candidate differs from current frozen risk resolver")
    experiment = canonical_digest(
        {"source": args.source_revision, "task": args.task, "attempt": task["attempt"], "operation": args.operation_id}
    )
    marker = root / ".alk/host-launch" / ("probe-" + experiment + ".json")
    try:
        create_authority_bytes(
            marker,
            canonical_bytes(
                {
                    "schemaVersion": "agent-local-probe-attempt.v1",
                    "bindingDigest": selection["selectedBindingDigest"],
                    "operationId": args.operation_id,
                    "status": "DISPATCH_PENDING",
                    "retryAuthorized": False,
                }
            )
            + b"\n",
            root=root,
            private=True,
        )
    except FileExistsError:
        raise LifecycleError(
            "model-probe-already-attempted",
            "this diagnostic experiment already has an immutable attempt; reconcile its result",
        ) from None
    return _run_probe(args, root, inspected, selection, state_path, task, risk, marker)


def _require_probe_containment(argv: list[str], root: Path) -> None:
    if (
        "--sandbox" not in argv
        or argv[argv.index("--sandbox") + 1 :][:1] != ["read-only"]
        or any(
            flag in argv for flag in ("--full-auto", "--yolo", "--dangerously-bypass-approvals-and-sandbox", "--enable")
        )
    ):
        raise LifecycleError(
            "model-probe-containment-required", "diagnostic probe requires the ordinary read-only sandbox route"
        )
    if argv.count("--sandbox") != 1 or any(
        value.split("=", 1)[0] in {"sandbox_mode", "approval_policy"} for value in argv
    ):
        raise LifecycleError("model-probe-containment-required", "diagnostic sandbox settings must not conflict")
    stage_launch.require_probe_working_directory(argv, root)


def _probe_route_request(args: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    tier = manifest.get("specification", {}).get("tier")
    return {
        "schemaVersion": "agent-lifecycle-model-route-request.v1",
        "operationId": args.operation_id,
        "phase": "task-implementation",
        "sddTier": tier,
        "routingPolicy": "balanced",
        "capabilityRequirements": [],
        "targetContextWindow": "8k",
    }


def _run_probe(
    args: Any,
    root: Path,
    inspected: dict[str, Any],
    selection: dict[str, Any],
    state_path: Path,
    task: dict[str, Any],
    risk: dict[str, Any],
    marker: Path,
) -> dict[str, Any]:
    launch = launch_from_local_profile(
        profile_path=inspected["launchPath"],
        operation="managedTask",
        adapter_id=inspected["entry"]["adapterId"],
        session_id="binding-probe-"
        + canonical_digest({"operation": args.operation_id, "binding": selection["selectedBindingDigest"]})[:16],
        project_root=root,
        explicit_launch=True,
        state_path=state_path,
        manifest_path=Path(args.manifest),
        lock_path=Path(args.lock),
        task_id=args.task,
        operation_id=args.operation_id,
        source_revision=args.source_revision,
        risk_profile=risk,
        stage_binding=selection,
    )
    observation = build_probe_observation(
        availability=inspected["availability"],
        auth_revision_digest=inspected["authRevisionDigest"],
        launch=launch,
        now=int(time.time()),
        lineage={
            "operationId": args.operation_id,
            "sourceRevision": args.source_revision,
            "stateRevision": args.expected_revision,
            "taskId": args.task,
            "attempt": task["attempt"],
        },
        model_response=stage_launch.observe_codex_model_response(selection.get("localProcessResult")),
    )
    observation_path = root / ".alk/host-launch" / ("availability-" + selection["selectedBindingDigest"] + ".json")
    replace_authority_bytes(observation_path, canonical_bytes(observation) + b"\n", root=root)
    result = {
        "schemaVersion": "agent-binding-probe-result.v1",
        "status": observation["status"],
        "visibility": "PORTABLE" if args.portable else "LOCAL_ONLY",
        "stageBinding": portable_selection(selection),
        "launch": (
            {key: launch[key] for key in ("status", "receiptDigest", "hostLaunchStarted") if key in launch}
            if args.portable
            else launch
        ),
        "observation": observation,
        "taskAccepted": False,
        "qualityPromotionClaimed": False,
        "actualTokens": None,
        "actualUSD": None,
    }
    if not args.portable:
        result["localInvocation"] = selection.get("localInvocation")
        result["localProcessResult"] = selection.get("localProcessResult")
    local_result = {
        **result,
        "visibility": "LOCAL_ONLY",
        "launch": launch,
        "localInvocation": selection.get("localInvocation"),
        "localProcessResult": selection.get("localProcessResult"),
    }
    create_authority_bytes(
        marker.with_name(marker.stem + "-result.json"), canonical_bytes(local_result) + b"\n", root=root, private=True
    )
    return result
