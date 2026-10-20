"""Opt-in, in-process command spans; no runner, model call or authority."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    read_json_object,
    write_json_create,
)
from agent_lifecycle.contracts.authority_io import authority_location, hold_authority_directory
from agent_lifecycle.contracts.paths import (
    normalize_repo_path,
    read_stable_repository_file,
)
from agent_lifecycle.contracts.release_accounting_schemas import (
    COMMAND_RESOURCE_SCHEMA,
    COMMANDS,
    PHASES,
    validate_command_resource_receipt,
)

REQUEST_SCHEMA = "agent-command-resource-request.v1"
MAX_SPANS = 64
MAX_SOURCE_BYTES = 8 * 1024 * 1024
_ACTIVE: ContextVar[CommandMeasurement | None] = ContextVar(
    "alk_command_measurement", default=None,
)


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_measurement_request(request: Any) -> None:
    """Validate bounded input before touching the selected command."""
    fields = {
        "schemaVersion", "operationDigest", "sourceRevision", "sourceRoot",
        "sourceFiles", "sourceSnapshotDigest", "phase",
    }
    if not isinstance(request, dict) or set(request) != fields:
        raise LifecycleError("command-measurement-request-invalid", "Invalid measurement request")
    revision = request["sourceRevision"]
    if (
        request["schemaVersion"] != REQUEST_SCHEMA
        or not _digest(request["operationDigest"])
        or not _digest(request["sourceSnapshotDigest"])
        or not isinstance(request["phase"], str) or request["phase"] not in PHASES
        or not isinstance(revision, str) or len(revision) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in revision)
        or not isinstance(request["sourceRoot"], str)
        or not request["sourceRoot"] or len(request["sourceRoot"]) > 4096
    ):
        raise LifecycleError("command-measurement-request-invalid", "Invalid measurement binding")
    files = request["sourceFiles"]
    if not isinstance(files, dict) or not 1 <= len(files) <= 64:
        raise LifecycleError("command-measurement-source-invalid", "Invalid source inventory")
    for name, digest in files.items():
        normalize_repo_path(name, label="measurement source")
        if not _digest(digest):
            raise LifecycleError("command-measurement-source-invalid", "Invalid source digest")
    if canonical_digest(files) != request["sourceSnapshotDigest"]:
        raise LifecycleError("command-measurement-source-invalid", "Source inventory binding differs")


def _verify_source(request: dict[str, Any]) -> None:
    total = 0
    from agent_lifecycle.contracts import sha256_hex

    for name, digest in request["sourceFiles"].items():
        data = read_stable_repository_file(
            Path(request["sourceRoot"]), name,
            max_bytes=MAX_SOURCE_BYTES - total, label="measurement source",
        )
        total += len(data)
        if total > MAX_SOURCE_BYTES or sha256_hex(data) != digest:
            raise LifecycleError("command-measurement-source-changed", "Source bytes differ")


class CommandMeasurement:
    """One synchronous process span; nested inclusive time is subtracted once."""

    def __init__(self, request: dict[str, Any], argv: list[str]) -> None:
        validate_measurement_request(request)
        if not argv or argv[0] not in COMMANDS:
            raise LifecycleError("command-measurement-command-invalid", "Unknown command label")
        _verify_source(request)
        self.request = dict(request)
        self.command = argv[0]
        self.argv_digest = canonical_digest(argv)
        self.parent: CommandMeasurement | None = _ACTIVE.get()
        self.count: int = 1
        self.thread: int = threading.get_ident()
        if self.parent is not None:
            expected = ("sourceRevision", "sourceSnapshotDigest")
            if (
                self.parent.thread != threading.get_ident()
                or any(request[key] != self.parent.request[key] for key in expected)
                or self.parent.count >= MAX_SPANS
            ):
                raise LifecycleError("command-measurement-parent-invalid", "Incompatible parent span")
            ancestor: CommandMeasurement | None = self.parent
            while ancestor is not None:
                if ancestor.count >= MAX_SPANS:
                    raise LifecycleError("command-measurement-limit", "Too many nested spans")
                ancestor = ancestor.parent
            ancestor = self.parent
            while ancestor is not None:
                ancestor.count += 1
                ancestor = ancestor.parent
        self.span_digest = canonical_digest(uuid4().hex)
        self.clock_domain: str = (
            self.parent.clock_domain if self.parent is not None
            else canonical_digest(uuid4().hex)
        )
        self.children: list[dict[str, Any]] = []
        self.token: Any = None
        self.start_wall = 0
        self.start_cpu = 0

    def start(self) -> None:
        if self.token is not None:
            raise LifecycleError("command-measurement-already-started", "Span already started")
        self.token = _ACTIVE.set(self)
        self.start_wall = time.perf_counter_ns()
        self.start_cpu = time.process_time_ns()

    def finish(self, exit_code: int) -> dict[str, Any]:
        end_cpu = time.process_time_ns()
        end_wall = time.perf_counter_ns()
        if self.token is None or _ACTIVE.get() is not self:
            raise LifecycleError("command-measurement-not-active", "Span is not active")
        _ACTIVE.reset(self.token)
        self.token = None
        child_wall = sum(child["inclusiveWallNs"] for child in self.children)
        child_cpu = sum(child["inclusiveCpuNs"] for child in self.children)
        body = {
            "schemaVersion": COMMAND_RESOURCE_SCHEMA, "status": "PASS",
            "operationDigest": self.request["operationDigest"],
            "sourceRevision": self.request["sourceRevision"],
            "sourceRevisionBasis": "DECLARED_BASE",
            "sourceSnapshotDigest": self.request["sourceSnapshotDigest"],
            "sourceBinding": "VERIFIED_SELECTED_BYTES",
            "command": self.command, "phase": self.request["phase"],
            "argvDigest": self.argv_digest, "spanDigest": self.span_digest,
            "parentSpanDigest": self.parent.span_digest if self.parent else None,
            "clockDomainDigest": self.clock_domain,
            "startWallNs": self.start_wall, "endWallNs": end_wall,
            "startCpuNs": self.start_cpu, "endCpuNs": end_cpu,
            "inclusiveWallNs": end_wall - self.start_wall,
            "exclusiveWallNs": end_wall - self.start_wall - child_wall,
            "inclusiveCpuNs": end_cpu - self.start_cpu,
            "exclusiveCpuNs": end_cpu - self.start_cpu - child_cpu,
            "exitCode": exit_code, "outcome": "SUCCEEDED" if exit_code == 0 else "FAILED",
            "childCpu": {"status": "UNAVAILABLE", "value": None},
            "modelTokens": {"status": "UNAVAILABLE", "value": None},
            "children": self.children, "authorityClaimed": False,
            "productionPromotionClaimed": False,
        }
        receipt = {**body, "receiptDigest": canonical_digest(body)}
        validation = validate_command_resource_receipt(receipt)
        if validation["status"] != "PASS":
            raise LifecycleError("command-measurement-invalid", "Collected span failed validation")
        if self.parent is not None:
            self.parent.children.append(receipt)
        return receipt


def collect_command(
    request: dict[str, Any], argv: list[str], invoke: Callable[[], int],
) -> tuple[int, dict[str, Any]]:
    """Measure one real invocation; exceptions remain exceptions, without retry."""
    measurement = CommandMeasurement(request, argv)
    measurement.start()
    try:
        code = invoke()
    except BaseException as exc:
        code = exc.code if isinstance(exc, SystemExit) and type(exc.code) is int else 2
        measurement.finish(code)
        raise
    return code, measurement.finish(code)


def run_measured_command(
    request_path: Path, output_path: Path, argv: list[str], invoke: Callable[[], int],
) -> int:
    """Check destination first; publication failure explicitly preserves effects."""
    request = read_json_object(request_path, label="command measurement request")
    measurement = CommandMeasurement(request, argv)
    authority_location(output_path)
    with hold_authority_directory(output_path.parent, writable=True):
        if output_path.exists() or output_path.is_symlink():
            raise LifecycleError("command-measurement-output-exists", "Output must be new")
        measurement.start()
        code = 2
        try:
            code = invoke()
        except SystemExit as exc:
            code = exc.code if type(exc.code) is int else 2
            raise
        finally:
            receipt = measurement.finish(code)
            try:
                write_json_create(output_path, receipt)
            except (LifecycleError, OSError):
                raise LifecycleError(
                    "command-measurement-publication-failed",
                    "Command already executed; receipt publication failed. Do not repeat automatically.",
                    {"commandExecuted": True, "commandExitCode": code,
                     "receiptDigest": receipt["receiptDigest"]},
                ) from None
    return code


def command_accounting_entries(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize exclusive process spans into existing release-accounting entries."""
    from agent_lifecycle.metrics.workflow_economics import build_workflow_metric_set

    seen: set[str] = set()
    entries: list[dict[str, Any]] = []

    def visit(receipt: dict[str, Any]) -> None:
        if receipt["spanDigest"] in seen:
            raise LifecycleError("command-measurement-duplicate", "Repeated command span")
        seen.add(receipt["spanDigest"])
        view = {"model": "implementation", "review": "audit",
                "remediation": "postAuditRemediation"}.get(receipt["phase"], "alkProcess")
        def measured(value: int) -> dict[str, Any]:
            return {"status": "MEASURED", "value": value, "additive": True}
        entries.append({
            "entryId": receipt["spanDigest"], "view": view,
            "costCategory": "productValidation" if view == "audit" else (
                "implementation" if view in {"implementation", "postAuditRemediation"}
                else "pipelineCompliance"
            ),
            "scope": {"kind": "command-exclusive", "id": receipt["spanDigest"], "additive": True},
            "metrics": {"tokens": {"status": "UNAVAILABLE", "value": None, "additive": True},
                        "steps": measured(1),
                        "elapsedWallMs": measured(receipt["exclusiveWallNs"] // 1_000_000),
                        "computeMs": measured(receipt["exclusiveCpuNs"] // 1_000_000)},
            "workflowMetrics": build_workflow_metric_set(inferred_measured={
                "toolCalls": 1, "toolWallMs": receipt["exclusiveWallNs"] // 1_000_000,
                "parallelComputeMs": receipt["exclusiveCpuNs"] // 1_000_000,
            }),
        })
        for child in receipt["children"]:
            visit(child)

    if not isinstance(receipts, list) or not 1 <= len(receipts) <= MAX_SPANS:
        raise LifecycleError("command-measurement-limit", "A bounded receipt list is required")
    source = None
    for receipt in receipts:
        if validate_command_resource_receipt(receipt)["status"] != "PASS" or receipt["parentSpanDigest"] is not None:
            raise LifecycleError("command-measurement-invalid", "Complete root spans are required")
        binding = (receipt["sourceRevision"], receipt["sourceSnapshotDigest"])
        if source is not None and binding != source:
            raise LifecycleError("command-measurement-source-mismatch", "Incompatible command sources")
        source = binding
        start = len(entries)
        visit(receipt)
        for entry in entries[start:]:
            entry["sourceArtifactDigest"] = canonical_digest(receipt)
    if len(seen) > MAX_SPANS:
        raise LifecycleError("command-measurement-limit", "Too many command spans")
    return entries
