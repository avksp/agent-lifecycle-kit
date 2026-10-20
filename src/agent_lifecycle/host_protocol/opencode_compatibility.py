"""OpenCode family policy, separate from process transport and host authority."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.launch_qualification import (
    observed_version,
    stable_version,
    version_policy_accepts,
    version_policy_bounds,
)


def opencode_family(version_output: str) -> tuple[str, int]:
    version = observed_version(version_output)
    if version is None or stable_version(version)[0] not in (1, 2):
        raise LifecycleError(
            "opencode-version-unsupported", "An unambiguous stable OpenCode 1.x or 2.x version is required"
        )
    return version, stable_version(version)[0]


def help_commands(major: int) -> dict[str, tuple[list[str], list[str]]]:
    """Return command-specific discovery, never infer support from exit zero."""
    if major not in (1, 2):
        raise LifecycleError("opencode-version-unsupported", "Unsupported OpenCode family")
    return {
        "run": (
            ["run", "--help"],
            [
                "opencode run",
                "--format",
                "json",
                "--model",
                "--auto",
                *(["--dir"] if major == 1 else ["--standalone", "provider/model#variant", "--file", "--title"]),
            ],
        ),
        "export": (
            ["export", "--help"] if major == 1 else ["session", "export", "--help"],
            ["opencode export"] if major == 1 else ["opencode session export", "--sanitize"],
        ),
        "stats": (["stats", "--help"], ["opencode stats", *(["--json"] if major == 2 else [])]),
    }


def effective_qualification(
    version_output: str,
    *,
    surfaces_ok: bool,
    source_revision: str | None = None,
    operation: str = "inspection",
    accepted_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Only an applicable accepted source/operation binding can yield VERIFIED."""
    try:
        version, major = opencode_family(version_output)
    except LifecycleError:
        return {"status": "UNSUPPORTED", "observedVersion": None, "family": None, "evidenceScope": "none"}
    status, scope = (
        ("COMPATIBLE_UNVERIFIED", "version-and-command-discovery-only")
        if surfaces_ok
        else ("UNSUPPORTED", "incompatible-command-surface")
    )
    if surfaces_ok and accepted_evidence is not None:
        policy = accepted_evidence.get("hostVersionPolicy")
        try:
            if not isinstance(policy, dict):
                raise ValueError("missing tested range")
            bounds = version_policy_bounds(policy)
        except ValueError:
            return {
                "status": "UNSUPPORTED",
                "observedVersion": version,
                "family": f"{major}.x",
                "evidenceScope": "invalid-tested-range",
            }
        evidence = accepted_evidence.get("evidenceIds")
        if (
            bounds is not None
            and version_policy_accepts(policy, version)
            and accepted_evidence.get("status") == "ACCEPTED"
            and source_revision is not None
            and accepted_evidence.get("sourceRevision") == source_revision
            and accepted_evidence.get("operation") == operation
            and isinstance(evidence, list)
            and evidence
            and all(isinstance(item, str) and item for item in evidence)
        ):
            status, scope = "VERIFIED", "accepted-source-operation-and-version-bound-live-evidence"
    return {"status": status, "observedVersion": version, "family": f"{major}.x", "evidenceScope": scope}


def model_arguments(major: int, model: str | None, variant: str | None) -> list[str]:
    """Resolve a single model route without silently changing variant identity."""
    if major not in (1, 2) or (variant is not None and model is None):
        raise LifecycleError("opencode-model-selection-invalid", "Model and variant require a supported explicit route")
    if model is None:
        return []
    if (
        re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._+-]*/[A-Za-z0-9][A-Za-z0-9._:/+-]*(?:#[A-Za-z0-9][A-Za-z0-9._-]*)?",
            model,
            re.ASCII,
        )
        is None
    ):
        raise LifecycleError("opencode-model-selection-invalid", "A well-formed provider/model route is required")
    if variant is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", variant, re.ASCII) is None:
        raise LifecycleError("opencode-model-selection-invalid", "A well-formed variant is required")
    base, separator, embedded = model.partition("#")
    if any(not part for part in base.split("/")):
        raise LifecycleError("opencode-model-selection-invalid", "Model route components must be nonempty")
    if variant and separator and variant != embedded:
        raise LifecycleError("opencode-model-variant-conflict", "Conflicting or malformed model variant")
    selected = variant or embedded
    if major == 2:
        return ["--model", base + (f"#{selected}" if selected else "")]
    return ["--model", base, *(["--variant", selected] if selected else [])]


def run_arguments(
    *,
    binary: str,
    major: int,
    message: str,
    directory: str,
    title: str,
    model: str | None = None,
    variant: str | None = None,
    files: tuple[str, ...] = (),
    auto_approve: bool = False,
) -> list[str]:
    if not message.strip() or message.startswith("-") or not title.strip():
        raise LifecycleError(
            "opencode-run-input-invalid", "A positional message and unique invocation title are required"
        )
    model_args = model_arguments(major, model, variant)
    return [
        binary,
        "run",
        message,
        "--format=json",
        "--title",
        title,
        *(["--dir", directory] if major == 1 else ["--standalone"]),
        *model_args,
        *(f"--file={path}" for path in files),
        *(["--auto"] if auto_approve else []),
    ]
