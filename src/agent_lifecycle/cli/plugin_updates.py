"""Bounded advisory plugin-update CLI; no native installation authority."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.plugin_update_validation import (
    MAX_UPDATE_BYTES,
    UPDATE_FORBIDDEN_ROOTS,
    read_update_json,
    require_update,
    validate_plan_inventory,
    validate_update_report,
    validate_update_request,
)


def add_plugin_update_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = subparsers.add_parser("plugin-update", help="bounded plugin discovery and read-only plan advice")
    actions = group.add_subparsers(dest="plugin_update_command", required=True)
    for action in ("check", "assess", "offer", "install", "reconcile"):
        parser = actions.add_parser(action)
        parser.add_argument("--request", required=True)
        parser.add_argument("--out")
        if action == "check":
            parser.add_argument("--cache")
        elif action == "assess":
            parser.add_argument("--release", required=True)
            parser.add_argument("--inventory", required=True)
            parser.add_argument("--repository-root", default=".")
        elif action == "offer":
            parser.add_argument("--assessment", required=True)
        elif action == "install":
            parser.add_argument("--offer", required=True)


def _protected_path(name: str, inputs: set[str]) -> str:
    name = normalize_repo_path(name)
    require_update(name not in inputs, "output/cache aliases an input")
    require_update(name.split("/")[0].casefold() not in UPDATE_FORBIDDEN_ROOTS, "unsafe output scope")
    require_update(
        not name.casefold().endswith((".state.json", ".lock.json", "plan.manifest.json")),
        "output cannot use authority filename",
    )
    return name


def _output_preflight(root: Path, output: str | None, inputs: set[str]) -> str | None:
    if output is None:
        return None
    name = _protected_path(output, inputs)
    path = root / name
    require_update(not path.exists() and not path.is_symlink(), "output already exists")
    parent = path.parent
    while parent != root:
        require_update(not parent.is_symlink(), "output parent is a symlink")
        parent = parent.parent
    return name


def _subject_inputs(action: str, data: dict[str, Any]) -> set[str]:
    subjects: set[str] = set()
    if action == "assess":
        for item in data.get("plans", []):
            if isinstance(item, dict):
                subjects.update(normalize_repo_path(path) for path in item.values() if isinstance(path, str))
    elif action == "offer":
        plans = data["details"].get("plans", [])
        require_update(isinstance(plans, list) and len(plans) <= 32, "invalid assessment plan count")
        for item in plans:
            if isinstance(item, dict) and isinstance(item.get("inputSHA256"), dict):
                subjects.update(normalize_repo_path(path) for path in item["inputSHA256"])
    return subjects


def _write_update_report(root: Path, output: str | None, payload: dict[str, Any]) -> None:
    validate_update_report(payload)
    body = canonical_bytes(payload) + b"\n"
    require_update(len(body) <= MAX_UPDATE_BYTES, "update output exceeds256KiB")
    if output is not None:
        require_update(
            payload["action"] != "assess" or payload["details"].get("assessmentComplete") is True,
            "incomplete assessment cannot write --out; omit --out for its diagnostic report",
            code="plugin-update-incomplete-assessment-output",
        )
        create_authority_bytes(root / output, body, root=root, private=True)


def dispatch_plugin_updates(args: argparse.Namespace) -> dict[str, Any]:
    from agent_lifecycle.adapter_sessions.plugin_updates import (
        offer_plugin_update,
        reconcile_plugin_update,
        refuse_plugin_install,
    )
    from agent_lifecycle.diagnostics.plugin_updates import check_plugin_updates, store_update_cache
    from agent_lifecycle.planning.update_impact import assess_plugin_update

    action = args.plugin_update_command
    root = Path(getattr(args, "repository_root", ".")).absolute()
    fields = [key for key in ("request", "release", "inventory", "assessment", "offer") if hasattr(args, key)]
    names = {key: normalize_repo_path(getattr(args, key)) for key in fields}
    inputs = set(names.values())
    cache_name = getattr(args, "cache", None)
    if cache_name:
        cache_name = _protected_path(cache_name, inputs)
        inputs.add(cache_name)
    output = _output_preflight(root, args.out, inputs)
    data = {key: read_update_json(root, name) for key, name in names.items()}
    request = validate_update_request(data["request"])
    if action == "assess":
        validate_plan_inventory(data["inventory"])
    elif action in ("offer", "install"):
        validate_update_report(data["assessment"] if action == "offer" else data["offer"])
    inputs.update(_subject_inputs(action, data.get("inventory", data.get("assessment", {}))))
    output = _output_preflight(root, output, inputs)
    if action == "check":
        reads_cache = request.get("mode", "manual") not in ("off", "notify", "safe-auto")
        cache = (
            read_update_json(root, cache_name) if reads_cache and cache_name and (root / cache_name).exists() else None
        )
        payload = check_plugin_updates(request, cache=cache)
        if cache_name and payload["details"].get("cacheUpdated") is True:
            store_update_cache(root, cache_name, payload["details"]["cache"], inputs=tuple(names.values()))
    elif action == "assess":
        payload = assess_plugin_update(request, data["release"], data["inventory"], repository_root=root)
    elif action == "offer":
        payload = offer_plugin_update(request, data["assessment"], repository_root=root)
    elif action == "install":
        payload = refuse_plugin_install(request, data["offer"])
    elif action == "reconcile":
        payload = reconcile_plugin_update(request)
    else:
        raise LifecycleError("command-not-implemented", "plugin-update action is not implemented")
    _write_update_report(root, output, payload)
    return payload
