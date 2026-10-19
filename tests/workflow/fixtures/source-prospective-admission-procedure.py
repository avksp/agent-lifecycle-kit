"""Reviewed coordinator validation procedure; it performs no financial writes."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.limited_usage import (
    _HEAD_PATH, _read_ref, _WINDOW, _window,
    load_frozen_source_policy,
)
from agent_lifecycle.adapter_sessions.bootstrap_r11 import (
    read_coordinator_cost_head, _r11_coordinator_source,
)


def require(ok, message):
    if not ok:
        raise LifecycleError("prospective-source-admission-invalid", message)


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
            "original clock must be UTC")
    return parsed


def require_live_admission_clocks(admission, state, task):
    """Repeat at validation, final return and immediately before publication."""
    observed = datetime.now(timezone.utc)
    require(observed < min(utc(admission["absoluteDeadlineUtc"]),
                           utc(state["runDeadlineAt"]), utc(task["attemptDeadlineAt"])),
            "original admission, run or attempt deadline expired")


def validate_prospective_admission(repository_root, manifest_path, task_id, admission,
                                   *, input_subject_ref):
    root = Path(repository_root).absolute()
    manifest_path = normalize_repo_path(manifest_path)
    initial = load_json_object(read_authority_bytes(root / manifest_path, root=root,
                                                   max_bytes=1_048_576), label="manifest")
    state_path = normalize_repo_path(initial["orchestration"]["stateFile"])
    state_raw = read_authority_bytes(root / state_path, root=root, max_bytes=1_048_576)
    state = load_json_object(state_raw, label="actual persisted source state")
    require(state["manifestPath"] == manifest_path and state["phase"] == "RUNNING",
            "current run/manifest differs")
    task = next((t for t in state["tasks"] if t["id"] == task_id), None)
    require(task is not None and task["status"] == "RUNNING", "current task is not running")
    selection = load_frozen_source_policy(root, state, task, adapter_id=task.get("adapterId"),
                                           adapter_host="codex")
    require(selection is not None and selection["manifest"] == initial,
            "current frozen Source authority differs")
    subject = load_json_object(_read_ref(root, input_subject_ref, limit=65_536),
                               label="actual immutable admission input subject")
    subject_digest = canonical_digest(subject)
    require(admission.get("inputSubjectRef") == input_subject_ref
            and admission.get("inputSubjectDigest") == subject_digest,
            "actual input subject differs")
    window_id = admission["originalWindowId"]
    require(_WINDOW.fullmatch(window_id + "/admission.json") is not None,
            "unsupported original window path")
    binding = _window(admission, window_id, "ADMISSION")
    require(binding is not None, "prospective Source binding is missing")
    route = task.get("attemptModelRoute") or {}
    expected = {"runId": state["runId"], "packageId": state["packageId"],
        "taskId": task_id, "attempt": task["attempt"], "planDigest": state["planDigest"],
        "sourceRevision": state["sourceRevision"], "routeDecisionDigest": route.get("decisionDigest"),
        "semanticOperationId": route.get("operationId"),
        "sourceUsagePolicyDigest": selection["policyDigest"],
        "sourceInputSubjectDigest": subject_digest, "originalWindowId": window_id}
    require(all(binding[k] == v for k, v in expected.items()), "current Source tuple differs")
    owners = {(v["actorId"], v["role"]) for v in selection["prefix"]["ownerBindings"]}
    require((binding["actorId"], "coordinator") in owners
            and admission.get("actorId") == binding["actorId"]
            and admission.get("role") == "coordinator"
            and admission.get("originalCostScope") == "COORDINATOR_FINITE_SOURCE_AUTHORING_WINDOW",
            "original coordinator attribution differs")
    require(utc(admission["admittedAtUtc"]) >= max(utc(state["runStartedAt"]),
                                                    utc(task["attemptStartedAt"]))
            and utc(admission["absoluteDeadlineUtc"]) <= min(utc(state["runDeadlineAt"]),
                                                             utc(task["attemptDeadlineAt"]))
            ,
            "original current run/task clocks differ or expired")
    require_live_admission_clocks(admission, state, task)
    kwargs = {"ancestor_head_sha256": selection["policy"]["openingRef"]["sha256"]}
    before = read_coordinator_cost_head(root, **kwargs)
    primary = Path(before["primaryCheckout"])
    identity_keys = ("runId", "packageId", "taskId", "attempt", "semanticOperationId")
    identity = tuple(binding[k] for k in identity_keys)
    chain = list(reversed(before["ancestryHeadSha256s"]))
    for index, head_sha in enumerate(chain):
        if index == len(chain) - 1:
            raw = before["headRaw"]
        elif index == 0:
            raw = _read_ref(root, selection["policy"]["openingRef"], limit=65_536)
        else:
            path = str(Path(_HEAD_PATH).parent / "coordinator-cost-head-history" / (head_sha + ".json"))
            raw = read_authority_bytes(primary / path, root=primary, max_bytes=131_072)
        require(hashlib.sha256(raw).hexdigest() == head_sha, "verified financial ancestor changed")
        head = load_json_object(raw, label="verified ancestor")
        value, source_raw = _r11_coordinator_source(primary, head["sourcePath"])
        require(hashlib.sha256(source_raw).hexdigest() == head["sourceSha256"],
                "verified original source changed")
        old = value.get("sourceUsageBinding")
        require(not isinstance(old, dict) or tuple(old.get(k) for k in identity_keys) != identity,
                "current operation already has an original binding")
    after = read_coordinator_cost_head(root, **kwargs)
    require(before["headRaw"] == after["headRaw"]
            and before["ancestryHeadSha256s"] == after["ancestryHeadSha256s"]
            and state_raw == read_authority_bytes(root / state_path, root=root, max_bytes=1_048_576),
            "actual state or financial frontier changed")
    require_live_admission_clocks(admission, state, task)
    return {"status": "VALIDATED_BEFORE_PUBLICATION", "binding": binding,
            "stateSha256": hashlib.sha256(state_raw).hexdigest(),
            "financialHeadSha256": hashlib.sha256(before["headRaw"]).hexdigest(),
            "inputSubjectDigest": subject_digest, "financialWrites": 0,
            "wholeHistoricalProjectionQualified": False, "hostBudgetGuarantee": False}
