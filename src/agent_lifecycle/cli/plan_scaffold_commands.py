"""Create-only filesystem boundary for the S2 authoring scaffold."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.authority_io import create_authority_directory
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
    try:
        create_authority_directory(target, payloads, root=root)
    except LifecycleError as exc:
        if exc.code == "authority-directory-exists":
            raise LifecycleError("scaffold-output-exists", "scaffold destination already exists", exc.details) from None
        raise
    except OSError:
        raise LifecycleError("scaffold-output-unavailable", "scaffold parent must already exist") from None
    return {
        "schemaVersion": "agent-plan-scaffold.v1",
        "status": "DRAFT",
        "manifest": f"{name}/plan.manifest.json",
        "filesWritten": manifest["planFiles"],
        "placeholders": sorted(set(scaffold_placeholders(manifest))),
        "authorityClaimed": False,
        "modelCallsStarted": False,
    }
