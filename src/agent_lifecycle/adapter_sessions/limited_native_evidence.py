"""Read-only checks for scoped native witnesses, never model dispatch authority.

A selected CLI invocation is observable; its internal provider request count,
whole host input and complete financial total remain unavailable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from datetime import timezone as timezone
from pathlib import Path

from agent_lifecycle.accounting.host_bridge import ARTIFACT_BYTES, PROFILE_BYTES, BoundedReader, _json
from agent_lifecycle.adapter_sessions.attempt_authority import _invocation_namespace, require_positive_attempt_result
from agent_lifecycle.adapter_sessions.ordinary_audit import verify_area_report
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path

ROLES = ("worker", "validator", "auditor", "retry", "coordinator", "closing")
POLARITIES = ("POSITIVE", "PRELAUNCH_REFUSAL", "STARTED_FAILURE", "STRONG_REFUSAL")
ROUTE = "codex-exact-prompt-v1"
CLAIM = "ALK_CONTROLLED_OUTBOUND_INPUT_FIT"
ADMISSION_PATH = "work/release-2-16/native-qualification-admission.json"
CAPACITY_OBLIGATION = "accounting.native.aggregate-104-105-selected-invocation-capacity"
PRODUCERS = (
    "src/agent_lifecycle/adapter_sessions/limited_native_evidence.py",
    "src/agent_lifecycle/adapter_sessions/launch_preflight.py",
    "tests/adapter_sessions/codex_limited_native_support.py",
    "tests/adapter_sessions/test_codex_exact_prompt.py",
)
LOCAL_FAULT_CODE = "import sys; sys.stdin.buffer.read(); sys.exit(7)"


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise LifecycleError("limited-native-evidence-unavailable", detail)


def read_ref(root: Path, ref: dict, reader: BoundedReader, limit: int = ARTIFACT_BYTES) -> bytes:
    require(isinstance(ref, dict) and set(ref) == {"path", "bytes", "sha256"}, "Closed artifact reference required")
    path = normalize_repo_path(ref["path"], label="native qualification artifact")
    raw = reader.read(root, path, limit)
    require(
        type(ref["bytes"]) is int and len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
        "Native artifact bytes changed",
    )
    return raw


def native_success_event(launch: dict) -> dict:
    """Require documented exec JSONL completion, without inferring a bill."""
    require(
        launch.get("status") == "PASS"
        and launch.get("processStarted") is True
        and type(launch.get("exitCode")) is int
        and launch["exitCode"] == 0,
        "No successful selected invocation",
    )
    events = []
    for line in str(launch.get("stdoutTail", "")).splitlines():
        try:
            value = _json(line.encode())
        except (LifecycleError, ValueError, UnicodeError):
            continue  # A bounded tail can start within an older line.
        if isinstance(value, dict):
            events.append(value)
    completed = [e for e in events if e.get("type") == "turn.completed"]
    require(
        len(completed) == 1 and not any(e.get("type") in {"error", "turn.failed"} for e in events),
        "Observed exec completion is missing, ambiguous or failed",
    )
    return completed[0]


def native_rows(root: Path, reader: BoundedReader) -> list[dict]:
    contract = _json(reader.read(root, "tasks/release-2-16/route-bootstrap-contract.json", ARTIFACT_BYTES))
    rows = contract["validation"]["limitedNativeMatrix"]["rows"]
    expected = {(r, p) for r in ROLES for p in POLARITIES}
    require(
        len(rows) == 24
        and {(r["role"], r["polarity"]) for r in rows} == expected
        and len({r["caseId"] for r in rows}) == 24,
        "Exact native24 inventory required",
    )
    return rows


def read_native_admission(
    root: Path, reader: BoundedReader, *, manifest: dict, state: dict, task: dict, live: bool
) -> tuple[dict, dict]:
    raw = reader.read(root, ADMISSION_PATH, PROFILE_BYTES)
    admission = _json(raw)
    lock_raw = reader.read(root, "tasks/release-2-16/plan.lock.json", ARTIFACT_BYTES)
    require(
        manifest.get("status") == "FROZEN"
        and admission["schemaVersion"] == "alk-r69-native-finite-admission.v1"
        and admission["status"] == "ADMITTED_PREAPPROVED_BY_USER"
        and admission["runId"] == state["runId"]
        and admission["taskId"] == task["id"]
        and admission["attemptId"] == str(task["attempt"])
        and task["status"] == "RUNNING"
        and admission["planDigest"] == canonical_digest(manifest) == state["planDigest"]
        and admission["lockSha256"] == hashlib.sha256(lock_raw).hexdigest()
        and type(admission["maxSelectedCodexInvocations"]) is int
        and 0 < admission["maxSelectedCodexInvocations"] <= 6
        and type(admission["tokenCap"]) is int
        and 0 < admission["tokenCap"] <= 1600000
        and type(admission["protectedCloseoutTokens"]) is int
        and 0 < admission["protectedCloseoutTokens"] < admission["tokenCap"]
        and admission["paidResponsesApiAllowed"] is False
        and admission["retryAuthorized"] is False
        and admission["costStatus"] == "UNAVAILABLE"
        and admission["fullUnknownHoldRetained"] is True,
        "Current finite native admission required",
    )
    # This qualification is a separately reviewed procedural boundary, not host telemetry.
    capacity = _json(read_ref(root, admission["capacityQualificationRef"], reader, PROFILE_BYTES))
    legacy_keys = {
        "status",
        "scope",
        "wholeHostUsageStatus",
        "qualifiedPriorStarts",
        "qualifiedRemainingCapacity",
        "planDigest",
        "lockSha256",
        "historyRefs",
    }
    ceiling = 6
    renewal_ref = None
    if set(capacity) != legacy_keys:
        require(
            set(capacity) == legacy_keys | {"aggregateSelectedInvocationCeiling", "renewalAuthorizationRef"},
            "Closed native capacity facts required",
        )
        renewal_ref = capacity["renewalAuthorizationRef"]
        renewal = _json(read_ref(root, renewal_ref, reader, PROFILE_BYTES))
        expected = {
            "schemaVersion": "alk-r216-native-capacity-renewal.v1",
            "authorizationKind": "EXPLICIT_EXACT_COUNT_USER_GRANT",
            "approved": True,
            "runId": state["runId"],
            "taskId": task["id"],
            "attemptId": str(task["attempt"]),
            "planDigest": state["planDigest"],
            "lockSha256": admission["lockSha256"],
            "priorSelectedStarts": capacity["qualifiedPriorStarts"],
            "additionalSelectedStarts": 6,
            "aggregateSelectedStartCeiling": capacity["aggregateSelectedInvocationCeiling"],
            "retryAuthorized": False,
            "paidResponsesApiAllowed": False,
        }
        require(
            isinstance(renewal, dict)
            and set(renewal) == set(expected) | {"userText"}
            and all(type(renewal[k]) is type(v) and renewal[k] == v for k, v in expected.items())
            and isinstance(renewal["userText"], str)
            and bool(renewal["userText"].strip())
            and type(capacity["aggregateSelectedInvocationCeiling"]) is int
            and capacity["aggregateSelectedInvocationCeiling"] in (12, 18)
            and type(capacity["qualifiedPriorStarts"]) is int
            and capacity["qualifiedPriorStarts"] == capacity["aggregateSelectedInvocationCeiling"] - 6
            and renewal_ref in capacity["historyRefs"],
            "Exact six-start renewal retaining all prior starts required",
        )
        ceiling = capacity["aggregateSelectedInvocationCeiling"]
    prior_ceiling = max(6, ceiling - 6)
    expected_scope = (
        "ALK_CONTROLLED_SELECTED_INVOCATIONS_104_105"
        if renewal_ref is None
        else "ALK_CONTROLLED_SELECTED_INVOCATIONS_104_105_AND_EXPLICIT_RENEWAL"
    )
    require(
        capacity["status"] == "PASS"
        and capacity["scope"] == expected_scope
        and capacity["wholeHostUsageStatus"] == "UNAVAILABLE_NOT_ZERO"
        and type(capacity["qualifiedPriorStarts"]) is int
        and 0 <= capacity["qualifiedPriorStarts"] <= prior_ceiling
        and type(capacity["qualifiedRemainingCapacity"]) is int
        and capacity["qualifiedRemainingCapacity"] == ceiling - capacity["qualifiedPriorStarts"]
        and admission["maxSelectedCodexInvocations"] <= capacity["qualifiedRemainingCapacity"]
        and capacity["planDigest"] == state["planDigest"]
        and capacity["lockSha256"] == admission["lockSha256"]
        and type(capacity["historyRefs"]) is list
        and bool(capacity["historyRefs"]),
        "Current cumulative controlled launch capacity remains unqualified",
    )
    # Facts never reference their covering review: both independent references
    # belong to the admission, avoiding a content-hash cycle.
    review_ref = admission["capacityReviewRef"]
    review = _json(read_ref(root, review_ref, reader, ARTIFACT_BYTES))
    verified = verify_area_report(root, review_id=admission["capacityReviewId"])
    require(
        verified["assurance"] == "PROCEDURAL_SAME_ACCOUNT"
        and verified["nativeAllowed"] is False
        and verified["report"] == review
        and verified["reportSha256"] == review_ref["sha256"]
        and review_ref["path"]
        == "work/release-2-16/evidence/ordinary-audit/" + admission["capacityReviewId"] + "/report.json"
        and review["reviewerId"] != admission["actorId"]
        and review["verdict"] == "PASS"
        and review["planDigest"] == state["planDigest"]
        and review["lockSha256"] == admission["lockSha256"]
        and verified["assignment"]["scopeId"] == "HOST_AND_TRANSPORT"
        and CAPACITY_OBLIGATION in review["coveredObligations"]
        and admission["capacityQualificationRef"] in review["coveredFiles"]
        and all(ref in review["coveredFiles"] for ref in capacity["historyRefs"]),
        "Capacity qualification has no matching observed independent review",
    )
    require(
        len({ref["path"] for ref in capacity["historyRefs"]}) == len(capacity["historyRefs"])
        and verified["snapshotRefs"],
        "Capacity history or observed origin is incomplete",
    )
    # Charge the origin consumer's reopened stable snapshot and the exact
    # reviewed history to the caller's shared content budget. Its own package
    # integrity/financial ancestry checks retain their existing internal bounds.
    for ref in [*capacity["historyRefs"], *verified["snapshotRefs"]]:
        read_ref(root, ref, reader)
    specs = admission["cases"]
    require(
        isinstance(specs, dict)
        and len(specs) == 24
        and len({s["operationId"] for s in specs.values()}) == 24
        and all(isinstance(s["operationId"], str) and s["operationId"] for s in specs.values()),
        "Distinct original task operation identities required",
    )
    if live:
        now = datetime.now(UTC)
        original = min(
            datetime.fromisoformat(x.replace("Z", "+00:00"))
            for x in (state["runDeadlineAt"], task["attemptDeadlineAt"])
        )
        admitted_deadline = datetime.fromisoformat(admission["absoluteDeadlineUtc"].replace("Z", "+00:00"))
        require(admitted_deadline == original and now < original, "Original native/task/run deadline expired")
    return admission, {"path": ADMISSION_PATH, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def verify_limited_native_case(
    root: Path,
    ref: dict,
    *,
    reader: BoundedReader,
    row: dict,
    manifest: dict,
    state: dict,
    task: dict,
    candidate_digest: str,
    admission: dict,
    admission_ref: dict,
    producer_refs: list[dict],
) -> dict:
    """A caller PASS, skipped test or local child cannot qualify native success."""
    case = _json(read_ref(root, ref, reader))
    return _verify_case(
        root,
        ref,
        case=case,
        reader=reader,
        row=row,
        manifest=manifest,
        state=state,
        task=task,
        candidate_digest=candidate_digest,
        admission=admission,
        admission_ref=admission_ref,
        producer_refs=producer_refs,
    )


def _verify_positive_native_transport(
    *,
    root: Path,
    case: dict,
    reader: BoundedReader,
    row: dict,
    spec: dict,
    admission: dict,
    admission_ref: dict,
    expected_path: str,
    result: dict,
    subject: dict,
    state: dict,
    directory: Path,
) -> None:
    slot_ref = case["capacitySlotRef"]
    slot = _json(read_ref(root, slot_ref, reader, PROFILE_BYTES))
    index = slot["slotIndex"]
    require(
        type(index) is int
        and 0 <= index < admission["maxSelectedCodexInvocations"]
        and (
            slot_ref["path"] == (Path(expected_path).parent.parent / "capacity-slots" / f"slot-{index}.json").as_posix()
        )
        and (
            slot
            == {
                "schemaVersion": "alk-r69-selected-invocation-slot.v1",
                "slotIndex": index,
                "caseId": row["caseId"],
                "operationId": spec["operationId"],
                "admissionSha256": admission_ref["sha256"],
                "claimSha256": case["claimRef"]["sha256"],
            }
        ),
        "No matching retained atomic selected-invocation slot",
    )
    observed = result["exactPrompt"]["observedProcessResult"]
    event = native_success_event(observed)
    require(
        result.get("status") == "PASS"
        and result.get("hostLaunchStarted") is True
        and (result.get("modelCallsStarted") is True),
        "Public native result is not a selected successful invocation",
    )
    require(
        case["selectedCodexInvocationsStarted"] == 1
        and subject["requestedClaim"] == CLAIM
        and (case["nativeSuccessEvent"] == event)
        and (case["localFault"] is False),
        "Selected native success was not observed",
    )
    names = {
        "intent": "prelaunch-intent.json",
        "start": "process-start.json",
        "input": "process-input.json",
        "transport": "transport-equivalence.json",
        "terminal": "attempt-result-terminal.json",
    }
    refs = case["nativeRefs"]
    require(set(refs) == set(names), "Native transport inventory differs")
    values = {}
    for key, name in names.items():
        require(root / refs[key]["path"] == directory / name, "Native transport belongs to another operation")
        values[key] = _json(read_ref(root, refs[key], reader))
    intent = values["intent"]
    terminal = require_positive_attempt_result(root, intent_path=directory / names["intent"], process_result=observed)
    exact = result["exactPrompt"]
    require(
        terminal == values["terminal"]
        and terminal["binding"]["operationId"] == case["operationId"]
        and (terminal["processResultSha256"] == canonical_digest(observed))
        and (intent["role"] == row["role"])
        and (intent["planDigest"] == state["planDigest"])
        and (exact["terminalResultSha256"] == refs["terminal"]["sha256"])
        and (exact["startReceiptSha256"] == refs["start"]["sha256"])
        and (exact["inputReceiptSha256"] == refs["input"]["sha256"])
        and (intent["finalPromptSha256"] == subject["finalPromptSha256"])
        and (intent["packetSha256"] == subject["packetSha256"])
        and (intent["binarySha256"] == subject["selectedBinarySha256"] == admission["selectedBinarySha256"])
        and (values["start"]["observedArgv"][0] == admission["selectedExecutable"])
        and (intent["commandIdentityHash"] == subject["argvDigest"])
        and (intent["configManifestSha256"] == subject["configSourceSha256"])
        and (intent["diagnosticObservation"]["rawSha256"] == subject["diagnosticCandidateSha256"])
        and (
            values["start"]["observedArgv"][values["start"]["observedArgv"].index("-m") + 1] == subject["selectedModel"]
        ),
        "Native success and observed transport are not joined",
    )


def _verify_local_started_failure(
    *,
    root: Path,
    case: dict,
    reader: BoundedReader,
    spec: dict,
    admission: dict,
    expected_path: str,
    result: dict,
    subject: dict,
    task: dict,
    polarity: str,
) -> None:
    require(case.get("capacitySlotRef") is None, "Local child cannot acquire selected invocation credit")
    require(
        polarity == "STARTED_FAILURE"
        and result.get("processStarted") is True
        and (result.get("status") == "FAIL")
        and (case["localFault"] is True)
        and (case["selectedCodexInvocationsStarted"] == 0)
        and (case["nativeSuccessEvent"] is None),
        "Local fault is not an observed started failure",
    )
    for key in (
        "packetSha256",
        "selectedBinarySha256",
        "selectedModel",
        "configSourceSha256",
        "diagnosticCandidateSha256",
    ):
        require(subject[key] is None, "Local fault cannot invent selected-Codex observations")
    refs = case["nativeRefs"]
    require(set(refs) == {"start", "input", "rawInput"}, "Local fault inventory differs")
    for key, suffix in (
        ("start", ".local-start.json"),
        ("input", ".local-input.json"),
        ("rawInput", ".local-stdin.bin"),
    ):
        require(refs[key]["path"] == expected_path + suffix, "Local fault witness belongs to another row")
    start = _json(read_ref(root, refs["start"], reader))
    delivered = _json(read_ref(root, refs["input"], reader))
    raw = read_ref(root, refs["rawInput"], reader, PROFILE_BYTES)
    require(
        start["processIdentityHash"] == result["startObservation"]["processIdentityHash"]
        and delivered == result["inputObservation"]
        and (delivered["processIdentityHash"] == start["processIdentityHash"])
        and (start["plannedStdinSha256"] == hashlib.sha256(raw).hexdigest() == subject["finalPromptSha256"])
        and (start["operationId"] == delivered["operationId"] == spec["operationId"])
        and (start["attemptId"] == delivered["attemptId"] == str(task["attempt"]))
        and (start["commandIdentityHash"] == subject["argvDigest"])
        and (start["argv"] == [admission["localPythonExecutable"], "-c", LOCAL_FAULT_CODE])
        and (start["argv"][0] != admission["selectedExecutable"])
        and (result["exitCode"] == 7),
        "Controlled local fault identity differs",
    )


def _verify_case(
    root: Path,
    ref: dict,
    *,
    case: dict,
    reader: BoundedReader,
    row: dict,
    manifest: dict,
    state: dict,
    task: dict,
    candidate_digest: str,
    admission: dict,
    admission_ref: dict,
    producer_refs: list[dict],
) -> dict:
    # Producer validates its in-memory candidate before create-only final write.
    # Public consumers always reopen and hash the actual final artifact above.
    spec = admission["cases"][row["caseId"]]
    subject = case["subject"]
    require(
        case.get("schemaVersion") == "alk-r69-native-case.v1"
        and case.get("status") == "PASS"
        and case.get("caseId") == row["caseId"]
        and case.get("executionClass") == row["executionClass"]
        and set(row["subjectRequired"]) <= set(subject)
        and subject["runId"] == state["runId"]
        and subject["taskId"] == task["id"]
        and subject["attemptId"] == str(task["attempt"])
        and subject["role"] == row["role"]
        and subject["planDigest"] == canonical_digest(manifest) == state["planDigest"]
        and subject["r69LockSha256"] == admission["lockSha256"]
        and subject["costStatus"] == "UNAVAILABLE"
        and case["alkCandidateDigest"] == candidate_digest
        and case["operationId"] == spec["operationId"]
        and case["admissionRef"] == admission_ref
        and case["producerRefs"] == producer_refs
        and case.get("providerModelRequestCount") is None
        and case.get("completeFinancialRun") is False
        and case.get("costStatus") == "UNAVAILABLE"
        and case.get("fullUnknownHoldRetained") is True
        and type(case["selectedCodexInvocationsStarted"]) is int,
        "Native case is not the current limited subject",
    )
    expected_path = row["receiptPathTemplate"].format(
        runId=state["runId"], taskId=task["id"], attemptId=str(task["attempt"])
    )
    require(ref["path"] == expected_path, "Native case path differs")
    claim = _json(read_ref(root, case["claimRef"], reader, PROFILE_BYTES))
    require(
        case["claimRef"]["path"] == expected_path + ".claim.json"
        and claim
        == {
            "schemaVersion": "alk-r69-native-case-claim.v1",
            "caseId": row["caseId"],
            "operationId": spec["operationId"],
            "admissionSha256": admission_ref["sha256"],
        },
        "Native create-once claim differs",
    )
    require(case["resultRef"]["path"] == expected_path + ".result.json", "Native result belongs to another row")
    result = _json(read_ref(root, case["resultRef"], reader))
    polarity = row["polarity"]
    ns = _invocation_namespace(state["runId"], task["id"], str(task["attempt"]), case["operationId"])
    directory = root / "work/release-2-16/evidence/codex-exact-prompt" / ns
    if polarity == "POSITIVE":
        _verify_positive_native_transport(
            root=root,
            case=case,
            reader=reader,
            row=row,
            spec=spec,
            admission=admission,
            admission_ref=admission_ref,
            expected_path=expected_path,
            result=result,
            subject=subject,
            state=state,
            directory=directory,
        )
    elif polarity in {"PRELAUNCH_REFUSAL", "STRONG_REFUSAL"}:
        require(case.get("capacitySlotRef") is None, "Refusal cannot acquire selected invocation credit")
        code = "codex-exact-packet-stale" if polarity == "PRELAUNCH_REFUSAL" else "codex-exact-route-required"
        require(
            result.get("status") == "BLOCKED"
            and result.get("hostLaunchStarted") is False
            and case["selectedCodexInvocationsStarted"] == 0
            and case["nativeSuccessEvent"] is None
            and case["localFault"] is False
            and case["nativeRefs"] == {}
            and code in {b["code"] for b in result["blockers"]},
            "Requested refusal was not observed",
        )
        for name in ("process-start.json", "process-input.json"):
            path = directory / name
            require(not path.exists() and not path.is_symlink(), "Refusal has an actual process receipt")
        require(
            subject["requestedClaim"] == (CLAIM if polarity == "PRELAUNCH_REFUSAL" else "COMPLETE_HOST_INPUT_FIT"),
            "Strong request was downgraded",
        )
        for key in (
            "finalPromptSha256",
            "selectedModel",
            "argvDigest",
            "configSourceSha256",
            "diagnosticCandidateSha256",
        ):
            require(subject[key] is None, "Unobserved refusal field cannot be fabricated")
    else:
        _verify_local_started_failure(
            root=root,
            case=case,
            reader=reader,
            spec=spec,
            admission=admission,
            expected_path=expected_path,
            result=result,
            subject=subject,
            task=task,
            polarity=polarity,
        )
    return case


def verify_native_observations(
    root: Path, payload: dict, *, reader: BoundedReader, manifest: dict, state: dict, task: dict, candidate_digest: str
) -> list[dict]:
    """Validate native24 exactly once, before any C21 sidecar or accepting write."""
    rows = native_rows(root, reader)
    admission, admission_ref = read_native_admission(root, reader, manifest=manifest, state=state, task=task, live=True)
    require(set(admission["cases"]) == {row["caseId"] for row in rows}, "Native admission row set differs")
    producer_refs = []
    for path in PRODUCERS:
        raw = reader.read(root, path, ARTIFACT_BYTES)
        producer_refs.append({"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    commands = payload["commands"]
    out = []
    for row in rows:
        matches = [c for c in commands if c["commandDigest"] == canonical_digest(row["command"])]
        require(
            len(matches) == 1
            and matches[0]["status"] == "PASS"
            and matches[0]["exitCode"] == 0
            and len(matches[0]["cases"]) == 1
            and matches[0]["cases"][0]["id"] == row["caseId"]
            and matches[0]["cases"][0]["status"] == "PASS",
            "Exact native per-case command result missing",
        )
        # A unittest skip can exit zero; only a complete current witness qualifies.
        out.append(
            verify_limited_native_case(
                root,
                matches[0]["cases"][0]["evidence"],
                reader=reader,
                row=row,
                manifest=manifest,
                state=state,
                task=task,
                candidate_digest=candidate_digest,
                admission=admission,
                admission_ref=admission_ref,
                producer_refs=producer_refs,
            )
        )
    selected = [c for c in out if c["selectedCodexInvocationsStarted"] == 1]
    require(
        len({c["capacitySlotRef"]["path"] for c in selected}) == len(selected)
        and sum(c["selectedCodexInvocationsStarted"] for c in out) <= admission["maxSelectedCodexInvocations"],
        "Aggregate selected invocation ceiling exceeded",
    )
    return out
