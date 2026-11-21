"""Create-only filesystem boundary for the S2 authoring scaffold."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.authority_io import hold_authority_directory
from agent_lifecycle.contracts.ownership_paths import repository_authority_name, require_declared_output_footprint
from agent_lifecycle.planning.scaffold import s2_scaffold, scaffold_placeholders


def create_plan_scaffold(
    *,
    out: str,
    artifact_root: str,
    repository_root: Path,
    author: str,
    owner: str,
    base_ref: str,
    base_sha: str,
) -> dict[str, Any]:
    """Create a new draft in an explicitly selected, previously absent directory."""
    root = repository_root.resolve(strict=True)
    name = repository_authority_name(root / out, root)
    artifacts = repository_authority_name(root / artifact_root, root)
    if any(part.startswith(".") for part in name.split("/")):
        raise LifecycleError("scaffold-output-protected", "scaffold cannot create packages under hidden paths")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base_sha):
        raise LifecycleError("scaffold-base-sha-invalid", "base SHA must be a complete Git object id")
    manifest, files = s2_scaffold(name, artifacts, author=author, owner=owner, base_ref=base_ref, base_sha=base_sha)
    require_declared_output_footprint(manifest, repository_root=root)
    target = root / name
    payloads = {filename: text.encode("utf-8") for filename, text in files.items()}
    payloads["plan.manifest.json"] = canonical_bytes(manifest) + b"\n"
    _write_scaffold(root, target, payloads)
    return {
        "schemaVersion": "agent-plan-scaffold.v1",
        "status": "DRAFT",
        "manifest": f"{name}/plan.manifest.json",
        "filesWritten": manifest["planFiles"],
        "placeholders": sorted(set(scaffold_placeholders(manifest))),
        "authorityClaimed": False,
        "modelCallsStarted": False,
    }


def _write_scaffold(root: Path, target: Path, payloads: dict[str, bytes]) -> None:
    try:
        with hold_authority_directory(target.parent, root=root, writable=True) as parent:
            try:
                parent.mkdir_child(target.name, 0o755)
            except FileExistsError:
                raise LifecycleError("scaffold-output-exists", "scaffold destination already exists") from None
            created = parent.stat_child(target.name)
            parent.sync()
            with hold_authority_directory(target, root=root, writable=True) as directory:
                held = os.fstat(directory.fd) if directory.fd is not None else directory.identity
                _require_scaffold_identity(created, held)
                for filename, data in payloads.items():
                    fd = directory.write_child(filename, append=False, mode=0o644)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                directory.sync()
                _require_scaffold_identity(created, parent.stat_child(target.name))
    except OSError:
        raise LifecycleError("scaffold-output-unavailable", "scaffold output could not be safely written") from None


def _require_scaffold_identity(created: os.stat_result, actual: os.stat_result | None) -> None:
    if actual is None or not os.path.samestat(created, actual):
        raise LifecycleError("scaffold-output-changed", "scaffold output directory identity changed")
