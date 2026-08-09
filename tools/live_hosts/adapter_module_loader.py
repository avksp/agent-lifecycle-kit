"""Contained loader for adapter-local usage normalizers."""

from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from agent_lifecycle.contracts import LifecycleError, sha256_hex
from agent_lifecycle.host_protocol import NormalizedUsage, validate_usage_normalization_profile

ROOT = Path(__file__).resolve().parents[2]
_ADAPTER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True, slots=True)
class LoadedUsageNormalizer:
    adapter_id: str
    status: str
    artifact_format: str
    max_artifact_bytes: int
    digest: str
    parse_usage: Callable[..., NormalizedUsage]


def load_adapter_usage_normalizer(
    adapter_id: str,
    *,
    repository_root: Path | None = None,
) -> LoadedUsageNormalizer:
    """Load only the normalizer declared inside one adapter directory."""

    if not isinstance(adapter_id, str) or not _ADAPTER_ID.fullmatch(adapter_id):
        raise LifecycleError("invalid-adapter-id", "adapter id is invalid")
    root = (repository_root or ROOT).resolve()
    adapter_root = root / "adapters" / adapter_id
    descriptor_path = adapter_root / "adapter.descriptor.json"
    if not descriptor_path.is_file() or descriptor_path.is_symlink():
        raise LifecycleError("adapter-usage-normalizer-descriptor", "adapter descriptor is missing or unsafe")
    descriptor = _read_json_object(descriptor_path)
    if descriptor.get("adapterId") != adapter_id:
        raise LifecycleError("adapter-usage-normalizer-descriptor", "descriptor adapter id does not match the requested adapter")
    profile = descriptor.get("usageNormalization")
    validation = validate_usage_normalization_profile(profile, adapter_id=adapter_id, host=descriptor.get("host"))
    if validation["status"] != "PASS" or not isinstance(profile, dict) or profile.get("status") == "UNSUPPORTED":
        raise LifecycleError(
            "adapter-usage-normalizer-unavailable",
            "adapter does not declare a loadable usage normalizer",
            {"blockers": validation["blockers"]},
        )
    declared_path = root / profile["path"]
    expected_path = adapter_root / "usage_normalizer.py"
    if declared_path != expected_path or not _contained_regular_file(declared_path, adapter_root):
        raise LifecycleError("adapter-usage-normalizer-path", "normalizer path is outside its adapter boundary")
    module = _load_module(adapter_id, declared_path)
    parser = getattr(module, "parse_usage", None)
    if not callable(parser):
        raise LifecycleError("adapter-usage-normalizer-entrypoint", "normalizer must export parse_usage")
    return LoadedUsageNormalizer(
        adapter_id=adapter_id,
        status=profile["status"],
        artifact_format=profile["artifactFormat"],
        max_artifact_bytes=profile["maxArtifactBytes"],
        digest=sha256_hex(declared_path.read_bytes()),
        parse_usage=parser,
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LifecycleError("adapter-usage-normalizer-descriptor", "adapter descriptor is unreadable") from error
    if not isinstance(value, dict):
        raise LifecycleError("adapter-usage-normalizer-descriptor", "adapter descriptor must be an object")
    return value


def _contained_regular_file(path: Path, adapter_root: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(adapter_root.resolve(strict=True))
    except (FileNotFoundError, ValueError, OSError):
        return False
    return path.is_file() and not path.is_symlink() and resolved == path.absolute()


def _load_module(adapter_id: str, path: Path) -> ModuleType:
    module_name = f"agent_lifecycle_adapter_{adapter_id.replace('-', '_')}_usage_normalizer"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise LifecycleError("adapter-usage-normalizer-load", "normalizer module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
