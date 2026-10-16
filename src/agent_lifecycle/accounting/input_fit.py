"""Source-bound ALK input selection and local fit checks.

These receipts describe only bytes assembled by ALK. They do not certify a
host's hidden input, context window, usage telemetry, or whole-call bound.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.context.rendering import render_context
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.token_estimation import estimate_tokens

SELECTION_SCHEMA = "alk-selected-source.v1"
FIT_SCHEMA = "alk-input-fit-receipt.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ROLES = frozenset({"worker", "validator", "auditor", "retry", "coordinator", "closing"})


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise LifecycleError("invalid-input-fit-identity", f"{label} must be lowercase SHA-256")
    return value


def _identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
        raise LifecycleError("invalid-input-fit-identity", f"{label} is required")
    return value


def _source_scope(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schemaVersion") != "alk-input-fit-contract.v1":
        raise LifecycleError("invalid-input-fit-contract", "unsupported input-fit contract")
    scope = contract.get("sourceScope")
    if not isinstance(scope, dict):
        raise LifecycleError("invalid-input-fit-contract", "source scope is missing")
    refs = scope.get("orderedContextRefs")
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
        raise LifecycleError("invalid-input-fit-contract", "ordered context refs are invalid")
    if len(refs) != len(set(refs)):
        raise LifecycleError("invalid-input-fit-contract", "ordered context refs are invalid")
    for path in refs:
        if normalize_repo_path(path, label="context ref") != path:
            raise LifecycleError("invalid-input-fit-contract", "context ref is not normalized")
    for key in (
        "maxExcerptsPerDispatch",
        "maxExcerptUtf8Bytes",
        "maxAggregateSelectedSourceUtf8Bytes",
        "maxSourcePathUtf8Bytes",
    ):
        if type(scope.get(key)) is not int or scope[key] <= 0:
            raise LifecycleError("invalid-input-fit-contract", f"{key} is invalid")
    return scope


def validate_context_ref_index(packet: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Keep the ordered source allow-list inside the full context index."""

    scope = _source_scope(contract)
    refs = packet.get("context", {}).get("refs") if isinstance(packet.get("context"), dict) else None
    allowed = scope["orderedContextRefs"]
    if (
        not isinstance(refs, list)
        or any(not isinstance(ref, str) for ref in refs)
        or len(set(refs)) != len(refs)
        or [ref for ref in refs if ref in allowed] != allowed
    ):
        raise LifecycleError(
            "context-ref-index-mismatch", "task context does not preserve the ordered source allow-list"
        )
    for ref in refs:
        try:
            normalized = normalize_repo_path(ref, label="context ref")
        except LifecycleError as exc:
            raise LifecycleError("context-ref-index-mismatch", "task context ref is not normalized") from exc
        if normalized != ref:
            raise LifecycleError("context-ref-index-mismatch", "task context ref is not normalized")
    result = {
        "schemaVersion": "alk-context-ref-index.v1",
        "status": "PENDING_SOURCE_SELECTION",
        "count": len(refs),
        "indexDigest": canonical_digest(refs),
    }
    return result


def select_source_excerpts(
    repository_root: Path,
    packet: dict[str, Any],
    contract: dict[str, Any],
    requests: list[dict[str, Any]],
    *,
    run_id: str,
    attempt_id: str,
    manifest_sha256: str,
    candidate_digest: str,
    estimator_id: str,
) -> dict[str, Any]:
    """Read exact declared byte ranges; reject stale or ambiguous selection."""

    index = validate_context_ref_index(packet, contract)
    scope = _source_scope(contract)
    plan = _validated_cast(dict[str, Any], packet.get("plan")) if isinstance(packet.get("plan"), dict) else {}
    task = _validated_cast(dict[str, Any], packet.get("task")) if isinstance(packet.get("task"), dict) else {}
    plan_digest = _digest(plan.get("planDigest"), "planDigest")
    task_id = _identity(task.get("id"), "taskId")
    _identity(run_id, "runId")
    _identity(attempt_id, "attemptId")
    _digest(manifest_sha256, "manifestSha256")
    _digest(candidate_digest, "candidateDigest")
    _identity(estimator_id, "estimatorId")
    if not isinstance(requests, list) or len(requests) > scope["maxExcerptsPerDispatch"]:
        raise LifecycleError("source-selection-overflow", "too many source excerpts")
    if any(not isinstance(request, dict) for request in requests):
        raise LifecycleError("invalid-source-selection", "source request must be an object")

    root = Path(repository_root).absolute()
    selected: list[dict[str, Any]] = []
    total = 0
    for request in requests:
        if request.get("candidateDigest") != candidate_digest or request.get("estimatorId") != estimator_id:
            raise LifecycleError("source-selection-identity-mismatch", "candidate or estimator changed")
        path = normalize_repo_path(_validated_cast(str, request.get("path")), label="selected source")
        if path not in scope["orderedContextRefs"]:
            raise LifecycleError("undeclared-source", "selected source is absent from contextRefs")
        if len(path.encode("utf-8")) > scope["maxSourcePathUtf8Bytes"]:
            raise LifecycleError("source-path-overflow", "selected source path exceeds limit")
        expected_file = _digest(request.get("fileSha256"), "fileSha256")
        expected_slice = _digest(request.get("selectedSha256"), "selectedSha256")
        start, end = request.get("startByte"), request.get("endByte")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise LifecycleError("invalid-source-range", "source range must be nonempty half-open bytes")
        try:
            data = read_authority_bytes(root / path, root=root, max_bytes=8_388_608)
        except OSError as exc:
            raise LifecycleError("source-unavailable", "selected source is unavailable") from exc
        if hashlib.sha256(data).hexdigest() != expected_file:
            raise LifecycleError("stale-source", "complete source file hash mismatch")
        if end > len(data):
            raise LifecycleError("invalid-source-range", "source range exceeds file length")
        piece = data[start:end]
        if len(piece) > scope["maxExcerptUtf8Bytes"]:
            raise LifecycleError("source-selection-overflow", "source excerpt exceeds byte limit")
        total += len(piece)
        if total > scope["maxAggregateSelectedSourceUtf8Bytes"]:
            raise LifecycleError("source-selection-overflow", "selected source total exceeds byte limit")
        try:
            data.decode("utf-8")
            text = piece.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LifecycleError("invalid-source-utf8-boundary", "source range is not UTF-8 aligned") from exc
        if hashlib.sha256(piece).hexdigest() != expected_slice:
            raise LifecycleError("stale-source-selection", "selected source bytes hash mismatch")
        selected.append(
            {
                "path": path,
                "fileSha256": expected_file,
                "startByte": start,
                "endByte": end,
                "selectedSha256": expected_slice,
                "utf8Bytes": len(piece),
                "text": text,
            }
        )
    receipt = {
        "schemaVersion": SELECTION_SCHEMA,
        "status": "SELECTED" if selected else "PENDING_SOURCE_SELECTION",
        "runId": run_id,
        "taskId": task_id,
        "attemptId": attempt_id,
        "planDigest": plan_digest,
        "manifestSha256": manifest_sha256,
        "candidateDigest": candidate_digest,
        "estimatorId": estimator_id,
        "contractDigest": canonical_digest(contract),
        "contextRefIndexDigest": index["indexDigest"],
        "indexOnlyCount": index["count"],
        "selected": selected,
        "selectedUtf8Bytes": total,
    }
    receipt["receiptDigest"] = canonical_digest(receipt)
    return receipt


def _revalidate_selection(
    repository_root: Path,
    contract: dict[str, Any],
    packet: dict[str, Any],
    selection: dict[str, Any],
    current_binding: dict[str, Any],
    estimator_id: str,
) -> None:
    if selection.get("schemaVersion") != SELECTION_SCHEMA or selection.get("status") != "SELECTED":
        raise LifecycleError("source-selection-pending", "required selected source is not established")
    body = {key: value for key, value in selection.items() if key != "receiptDigest"}
    if canonical_digest(body) != selection.get("receiptDigest"):
        raise LifecycleError("source-selection-mismatch", "selected source receipt changed")
    if selection.get("contractDigest") != canonical_digest(contract):
        raise LifecycleError("source-selection-mismatch", "input-fit contract changed")
    index = validate_context_ref_index(packet, contract)
    if (
        selection.get("contextRefIndexDigest") != index["indexDigest"]
        or type(selection.get("indexOnlyCount")) is not int
        or selection.get("indexOnlyCount") != index["count"]
    ):
        raise LifecycleError("source-selection-mismatch", "selected source context index changed")
    scope = _source_scope(contract)
    entries = selection.get("selected")
    if not isinstance(entries, list) or not entries or len(entries) > scope["maxExcerptsPerDispatch"]:
        raise LifecycleError("source-selection-mismatch", "selected source count is invalid")
    if any(not isinstance(entry, dict) for entry in entries):
        raise LifecycleError("source-selection-mismatch", "selected source entry is invalid")
    expected = {
        key: selection.get(key)
        for key in ("runId", "taskId", "attemptId", "planDigest", "manifestSha256", "candidateDigest")
    }
    expected["estimatorId"] = estimator_id
    if not isinstance(current_binding, dict) or any(
        current_binding.get(key) != value for key, value in expected.items()
    ):
        raise LifecycleError("input-fit-binding-mismatch", "current dispatch identity differs from source selection")
    plan = _validated_cast(dict[str, Any], packet.get("plan")) if isinstance(packet.get("plan"), dict) else {}
    task = _validated_cast(dict[str, Any], packet.get("task")) if isinstance(packet.get("task"), dict) else {}
    if selection.get("planDigest") != plan.get("planDigest") or selection.get("taskId") != task.get("id"):
        raise LifecycleError("source-selection-mismatch", "selected source lineage mismatch")
    if selection.get("estimatorId") != estimator_id:
        raise LifecycleError("source-selection-mismatch", "selected source estimator mismatch")
    root = Path(repository_root).absolute()
    selected_bytes = 0
    for entry in entries:
        path = normalize_repo_path(entry.get("path"), label="selected source")
        if path not in scope["orderedContextRefs"]:
            raise LifecycleError("undeclared-source", "selected source is absent from contextRefs")
        data = read_authority_bytes(root / path, root=root, max_bytes=8_388_608)
        start, end = entry.get("startByte"), entry.get("endByte")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > len(data):
            raise LifecycleError("source-selection-mismatch", "source range changed")
        piece = data[start:end]
        selected_bytes += len(piece)
        if len(piece) > scope["maxExcerptUtf8Bytes"] or selected_bytes > scope["maxAggregateSelectedSourceUtf8Bytes"]:
            raise LifecycleError("source-selection-overflow", "selected source exceeds byte limit")
        if not isinstance(entry.get("text"), str) or not isinstance(entry.get("fileSha256"), str):
            raise LifecycleError("source-selection-mismatch", "selected source identity is invalid")
        if (
            hashlib.sha256(data).hexdigest() != entry.get("fileSha256")
            or hashlib.sha256(piece).hexdigest() != entry.get("selectedSha256")
            or piece != entry.get("text", "").encode("utf-8")
        ):
            raise LifecycleError("stale-source-selection", "selected source changed before fit check")
    if selection.get("selectedUtf8Bytes") != selected_bytes:
        raise LifecycleError("source-selection-mismatch", "selected source byte count mismatch")


def assess_local_input_fit(
    repository_root: Path,
    contract: dict[str, Any],
    profile: dict[str, Any],
    packet: dict[str, Any],
    summary: dict[str, Any],
    selection: dict[str, Any],
    *,
    role: str,
    host_adapter_id: str,
    host_version: str,
    host_mode: str,
    estimator_id: str,
    instruction: Any,
    schema: Any,
    current_binding: dict[str, Any],
    latest_user: str = "",
    window: str = "16k",
) -> dict[str, Any]:
    """Check the supplied ALK components; never claim full host fit."""

    validate_context_ref_index(packet, contract)
    envelope = contract.get("commonEnvelope")
    if not isinstance(envelope, dict):
        raise LifecycleError("invalid-input-fit-contract", "common envelope is missing")
    if role not in _ROLES:
        raise LifecycleError("invalid-input-fit-role", "unsupported input role")
    if instruction in (None, "", [], {}):
        raise LifecycleError("missing-input-instruction", "ALK instruction is required")
    for label, value in (
        ("hostAdapterId", host_adapter_id),
        ("hostVersion", host_version),
        ("hostMode", host_mode),
        ("estimatorId", estimator_id),
    ):
        _identity(value, label)
    _revalidate_selection(repository_root, contract, packet, selection, current_binding, estimator_id)
    if window != envelope["targetWindow"]:
        raise LifecycleError("unqualified-input-window", "local input-fit route requires 16k")

    rendered = render_context(profile, packet, summary, latest_user=latest_user, window=window)
    instruction_bytes = canonical_bytes(instruction)
    schema_bytes = canonical_bytes(schema)
    model_input = {
        "renderedEnvelope": rendered["envelope"],
        "selectedSource": selection["selected"],
        "instruction": instruction,
        "schema": schema,
    }
    model_input_bytes = canonical_bytes(model_input)
    model_input_tokens = estimate_tokens(model_input)
    selected_tokens = estimate_tokens(selection["selected"])
    metadata_tokens = estimate_tokens({"instruction": instruction, "schema": schema})
    estimates = rendered["receipt"]["estimatedTokens"]
    checks = list(rendered["receipt"]["checks"])
    extra = (
        ("rendered-envelope-contract", model_input_tokens, envelope["maxRenderedEnvelopeEstimatedTokens"]),
        ("reserved-output-contract", model_input_tokens + envelope["reservedOutputEstimatedTokens"], 16_384),
        ("active-packet-contract", estimates["activePacket"], envelope["maxActivePacketEstimatedTokens"]),
        (
            "state-summary-contract",
            estimates["stateSummary"] + selected_tokens,
            envelope["maxStateSummaryEstimatedTokens"],
        ),
        ("evidence-summary-contract", estimates["evidenceSummary"], envelope["maxEvidenceSummaryEstimatedTokens"]),
        ("tool-output-contract", estimates["toolOutput"] + selected_tokens, envelope["maxToolOutputEstimatedTokens"]),
        ("instruction-bytes", len(instruction_bytes), envelope["maxInstructionCanonicalBytes"]),
        ("schema-bytes", len(schema_bytes), envelope["maxSchemaCanonicalBytes"]),
        ("context-bytes", len(model_input_bytes), envelope["maxContextBytes"]),
        ("metadata-tokens", metadata_tokens, envelope["maxMetadataEstimatedTokens"]),
    )
    checks.extend(
        {"id": name, "status": "PASS" if actual <= limit else "FAIL", "actual": actual, "limit": limit}
        for name, actual, limit in extra
    )
    status = "PASS_ALK_COMPONENTS_ONLY" if all(check["status"] == "PASS" for check in checks) else "REFUSE_OVERFLOW"
    receipt = {
        "schemaVersion": FIT_SCHEMA,
        "status": status,
        "scope": "ALK_CONTROLLED_INPUT_ONLY",
        "hostOwnedInput": "UNAVAILABLE",
        "wholeCallUpperBound": "UNAVAILABLE",
        "fullFinancial": False,
        "dispatchEntitlement": False,
        "role": role,
        "runId": selection["runId"],
        "taskId": selection["taskId"],
        "attemptId": selection["attemptId"],
        "planDigest": selection["planDigest"],
        "manifestSha256": selection["manifestSha256"],
        "candidateDigest": selection["candidateDigest"],
        "hostAdapterId": host_adapter_id,
        "hostVersion": host_version,
        "hostMode": host_mode,
        "contextProfileSha256": canonical_digest(profile),
        "window": window,
        "estimatorId": estimator_id,
        "selectedSourceDigests": [entry["selectedSha256"] for entry in selection["selected"]],
        "inputComponentDigests": {
            "renderedEnvelope": rendered["receipt"]["envelopeDigest"],
            "fullAlkModelInput": hashlib.sha256(model_input_bytes).hexdigest(),
            "instruction": hashlib.sha256(instruction_bytes).hexdigest(),
            "schema": hashlib.sha256(schema_bytes).hexdigest(),
            "sourceSelection": selection["receiptDigest"],
        },
        "checks": checks,
    }
    receipt["receiptDigest"] = canonical_digest(receipt)
    return receipt
