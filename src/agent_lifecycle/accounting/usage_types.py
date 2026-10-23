"""Neutral in-process source usage values; constructors confer no authority.

Only the frozen loaders select production readers. A protocol implementation
used by a unit fixture neither registers a ledger nor qualifies a native route.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_ref_shape


def require_source_usage(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise LifecycleError(code, message)


def source_reference(path: str, raw: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read_source_reference(root: Path, ref: dict[str, Any], *, limit: int) -> bytes:
    validate_source_ref_shape(ref)
    require_source_usage(ref["bytes"] <= limit, "scoped-usage-ref-invalid", "reference exceeds its bound")
    raw = read_authority_bytes(root / ref["path"], root=root, max_bytes=limit)
    require_source_usage(
        source_reference(ref["path"], raw) == ref, "scoped-usage-ref-invalid", "reference bytes differ"
    )
    return raw


@dataclass(frozen=True)
class SourceUsageContext:
    """Internal immutable value; its constructor is not an authority boundary."""

    manifestDigest: str
    stateDigest: str
    runId: str
    taskId: str
    adapterId: str
    adapterHost: str
    policyDigest: str
    appliesToTask: bool
    allowedModelClasses: tuple[str, ...]
    usageMode: str


class SourceUsageReader(Protocol):
    """Read-only source projection; no publishing or execution operations."""

    @property
    def head_path(self) -> str: ...

    def read_current(self) -> dict[str, Any]: ...

    def project(self, current: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class UsageContext(Mapping[str, Any]):
    """Checked inputs and a selected reader, with legacy mapping compatibility.

    These are same-process values, not capabilities. Production entrypoints
    must independently load the actual frozen manifest and lock every time.
    """

    root: Path
    policy: dict[str, Any]
    policy_digest: str
    prefix: dict[str, Any]
    registry_byte_limit: int
    source: SourceUsageReader
    inputs: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.inputs[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.inputs)

    def __len__(self) -> int:
        return len(self.inputs)


def serialize_source_registry(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
