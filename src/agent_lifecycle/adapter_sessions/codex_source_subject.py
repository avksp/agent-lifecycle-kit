"""Owned codex source subject helpers."""

from __future__ import annotations

import ast
import json
import re
import shlex
import stat
import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _file_sha
from agent_lifecycle.adapter_sessions.input_lifecycle import _PART, _sha
from agent_lifecycle.adapter_sessions.private_input import _read_private, _require
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import read_authority_bytes


def _r11_interaction_assignment_inventory() -> dict[str, dict[str, list[str]]]:
    assignments = {
        "OBSERVER_TERMINAL": {
            "process.py": ["run_process", "_observed_failure"],
            "bootstrap_r11.py": ["publish_attempt_result", "read_attempt_result"],
            "codex_exact_prompt.py": [
                "_complete_started_input",
                "reconcile_prelaunch_intents",
                "on_started",
                "on_input",
            ],
            "launch_preflight.py": ["_run_exact_managed_process"],
        },
        "COLLECTOR_FIRST_NATIVE": {
            "bootstrap_r11.py": [
                "_r11_role_authority",
                "_r11_role_schema_matches",
                "_r11_role_body",
                "_r11_role_source_content",
                "_r11_role_call_index",
                "_r11_role_project_calls",
                "_r11_role_source_projection",
                "_r11_role_identity",
                "_r11_role_subject",
                "_r11_role_shared_view_candidate",
                "_r11_role_request_candidate",
                "_r11_role_wire_request",
                "_r11_role_source_exposure",
                "_r11_role_envelope_fit",
                "read_source_review_envelope_fit",
                "_r11_role_material_authority",
                "_r11_role_source_basis",
                "build_source_review_shards",
                "_r11_role_integration_closure",
                "_r11_validate_coverage",
                "verify_source_review_body_and_reads",
                "SourceReviewTranscript",
                "verify_source_review_transport_records",
                "collect_source_review_support",
                "collect_source_review_transport",
                "collect_source_review_parent",
                "reconstruct_source_review",
                "_r11_reconstruct_review_basis",
                "_r11_review_authorities",
                "collect_source_review_evidence",
                "collect_source_review_shared",
                "_supervise_source_review_worker",
                "read_source_review_worker",
                "_R11AppServerPipe",
                "_exchange_source_review_rpc",
                "_run_source_review_app_server_worker",
                "_r11_role_send_basis",
                "read_source_review_cost",
                "reserve_source_review_cost",
                "_r11_role_request_seal",
                "read_source_review_request",
                "seal_source_review_request",
                "_r11_write_role_request_files",
                "_r11_read_role_request_files",
                "_r11_review_cost_basis",
                "_r11_cost_reservation",
                "_r11_cost_files",
                "_r11_cost_worker",
                "_r11_role_cost_chain",
                "_r11_cost_before_start",
                "settle_source_review_cost",
                "collect_source_review_accounted_evidence",
                "_supervise_costed_source_review_worker",
                "collect_source_review_host",
                "collect_source_review_supervised_evidence",
                "read_coordinator_cost_head",
                "advance_coordinator_cost_head",
                "_r11_coordinator_transition",
                "_r11_coordinator_source",
                "_r11_coordinator_head_value",
                "_r11_role_funding_record",
                "_r11_role_funding_origin",
                "admit_source_review_funding",
                "_r11_role_prefix_record",
                "_r11_global_role_prefixes",
                "publish_source_review_cost_prefix",
                "import_source_review_opening",
                "read_source_review_opening_origin",
                "collect_source_review_origin_bound_evidence",
                "prepare_source_review_threads",
                "collect_source_review_threads",
                "_r11_role_operation_start",
                "_r11_role_thread_preparation_basis",
                "_r11_role_request_origin",
                "_r11_role_original_deadline",
                "_r11_role_metadata_before_start",
                "_prepare_source_review_role_thread",
                "_run_source_review_thread_preparation",
                "capture_source_review_catalog",
                "read_source_review_catalog",
                "_r11_require_fresh_review_catalog",
                "prepare_source_review_inventory",
                "_r11_bind_request",
                "_r11_fresh_start",
                "_r11_seal_live_dispatch",
                "_r11_read_live_dispatch",
                "_r11_live_supervisor",
                "_r11_fixed_supervisor_reservation",
                "_r11_completed_assignment",
                "finalize_source_review_assignment",
                "_r11_closed_worker_funding",
                "collect_source_review_producer",
                "collect_source_review_qualified_evidence",
                "publish_source_review_composite",
                "read_source_review_composite",
                "_r11_composite_verified",
                "_r11_composite_schema",
                "_r11_composite_inventory",
                "install_source_review_composite",
                "_r11_native_composite",
                "_r11_lead_summary",
                "_r11_native_task",
                "_r11_fresh_operation",
                "_r11_fresh_deadline",
                "_r11_fresh_basis",
                "_r11_read_fresh_input",
                "_r11_fresh_exchange",
                "require_source_review_fresh_gate",
                "verify_source_review_fresh_gate",
                "prepare_source_review_worker",
                "_run_fixed_source_review_worker",
                "_supervise_fixed_source_review_worker",
                "_source_review_worker_main",
            ],
            "codex_exact_prompt.py": ["require_bootstrap_audit"],
        },
    }
    return assignments


def _matches_closed_schema(value: Any, schema: dict[str, Any]) -> bool:
    """Validate the limited JSON Schema vocabulary frozen in the route contract."""
    allowed = {
        "$schema",
        "title",
        "type",
        "required",
        "properties",
        "additionalProperties",
        "const",
        "enum",
        "pattern",
        "minLength",
        "minimum",
        "maximum",
        "minProperties",
        "maxProperties",
        "minItems",
        "maxItems",
        "items",
        "anyOf",
        "format",
        "description",
    }
    if (
        not isinstance(schema, dict)
        or not set(schema) <= allowed
        or any(not isinstance(schema.get(key), str) for key in ("$schema", "title") if key in schema)
    ):
        return False
    if "anyOf" in schema and not any(_matches_closed_schema(value, option) for option in schema["anyOf"]):
        return False
    kind = schema.get("type")
    if kind is not None:
        checks = {
            "object": lambda: isinstance(value, dict),
            "array": lambda: isinstance(value, list),
            "string": lambda: isinstance(value, str),
            "integer": lambda: type(value) is int,
            "boolean": lambda: type(value) is bool,
            "null": lambda: value is None,
        }
        if kind not in checks or not checks[kind]():
            return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            return False
        if not set(schema.get("required", [])) <= set(value):
            return False
        if len(value) < schema.get("minProperties", 0) or len(value) > schema.get("maxProperties", float("inf")):
            return False
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            rule = properties.get(key, extra)
            if rule is False or (isinstance(rule, dict) and not _matches_closed_schema(item, rule)):
                return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            return False
        if "items" in schema and any(not _matches_closed_schema(item, schema["items"]) for item in value):
            return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            return False
        if schema.get("format") == "date-time":
            try:
                if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    return False
            except ValueError:
                return False
        elif "format" in schema:
            return False
    return not (
        type(value) is int
        and (value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")))
    )


def _source_test_ids(root: Path, modules: list[str]) -> tuple[list[str], dict[str, str]]:
    """Re-derive static unittest IDs from the exact current test source bytes."""
    names: list[str] = []
    source_hashes: dict[str, str] = {}
    for module in modules:
        _require(
            module.startswith("tests.") and all(_PART.fullmatch(part) for part in module.split(".")),
            "codex-exact-bootstrap-subject-invalid",
            "validation module path is invalid",
        )
        relative = module.replace(".", "/") + ".py"
        raw = read_authority_bytes(root / relative, root=root, max_bytes=262_144)
        source_hashes[relative] = _sha(raw)
        try:
            tree = ast.parse(raw, filename=relative)
        except (SyntaxError, ValueError) as exc:
            raise LifecycleError(
                "codex-exact-bootstrap-subject-invalid", "validation test source cannot be parsed"
            ) from exc
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                (
                    isinstance(base, ast.Attribute)
                    and isinstance(base.value, ast.Name)
                    and base.value.id == "unittest"
                    and base.attr == "TestCase"
                )
                or (isinstance(base, ast.Name) and base.id == "TestCase")
                for base in node.bases
            ):
                continue
            names.extend(
                f"{module}.{node.name}.{method.name}"
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_")
            )
    _require(
        bool(names) and len(names) == len(set(names)),
        "codex-exact-bootstrap-subject-invalid",
        "validation test IDs are missing or repeated",
    )
    return sorted(names), source_hashes


def _r69h_check_one_test_dependency(
    root, path, rows, refusal, selected_ranges, fixture_names, inherited, imported_repo, local_helpers
):
    source = read_authority_bytes(root / path, root=root, max_bytes=262144)
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeError, SyntaxError, ValueError) as exc:
        raise LifecycleError(refusal, "selected test source cannot be parsed") from exc
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    module_helpers = {
        node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    imports: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            _require(
                node.level == 0 and node.module is not None, refusal, "relative test import is outside reviewed closure"
            )
            for alias in node.names:
                imports[alias.asname or alias.name] = node.module + "." + alias.name
    additions = [
        {
            "class": class_node.name,
            "method": node.name,
            "classFixtures": [],
            "sameClassCallees": [],
            "importedCalls": {},
        }
        for class_node in classes.values()
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_r69h_")
    ]
    _require(
        len({(row["class"], row["method"]) for row in rows + additions}) == len(rows) + len(additions),
        refusal,
        "new test collides with reviewed test roster",
    )
    for row in rows + additions:
        class_node = classes.get(row["class"])
        _require(class_node is not None, refusal, "selected test class missing")
        methods = {
            node.name: node for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        method = methods.get(row["method"])
        _require(
            method is not None and ("FULL" in selected_ranges[path] or row["method"] in selected_ranges[path]),
            refusal,
            "selected test body was not exposed",
        )
        fixtures = sorted(fixture_names & methods.keys())
        _require(
            fixtures == sorted(row["classFixtures"]),
            refusal,
            "new or changed class fixture requires reviewed oracle amendment",
        )
        pending = [method]
        visited = set()
        callees = set()
        referenced_module = set()
        imported = {}
        while pending:
            current = pending.pop()
            if id(current) in visited:
                continue
            visited.add(id(current))
            _require(
                not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(current)),
                refusal,
                "method-local import requires reviewed oracle amendment",
            )
            nested = {
                node.name
                for node in ast.walk(current)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not current
            }
            static_aliases = {
                target.id: imports[node.value.value.id] + "." + node.value.attr
                for node in ast.walk(current)
                if isinstance(node, ast.Assign) and len(node.targets) == 1
                for target in node.targets
                if isinstance(target, ast.Name)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and (node.value.value.id in imports)
            }
            for item in ast.walk(current):
                if not isinstance(item, ast.Call):
                    continue
                callee = item.func
                _require(
                    isinstance(callee, (ast.Name, ast.Attribute)),
                    refusal,
                    "dynamic test callee requires reviewed oracle amendment",
                )
                if isinstance(callee, ast.Name):
                    _require(
                        callee.id not in {"eval", "exec", "globals", "locals", "vars", "__import__"},
                        refusal,
                        "dynamic test callee requires reviewed oracle amendment",
                    )
                    if callee.id == "getattr" and item.args and isinstance(item.args[0], ast.Name):
                        _require(
                            item.args[0].id not in {"self", "cls"},
                            refusal,
                            "dynamic self/cls callee requires reviewed oracle amendment",
                        )
                    if callee.id in module_helpers:
                        referenced_module.add(callee.id)
                        pending.append(module_helpers[callee.id])
                    elif callee.id in imports:
                        imported[callee.id] = imports[callee.id]
                    elif callee.id in static_aliases:
                        imported[callee.id] = static_aliases[callee.id]
                    elif callee.id not in nested and callee.id in {
                        name.id
                        for name in ast.walk(current)
                        if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store)
                    }:
                        raise LifecycleError(refusal, "dynamic local test callee")
                elif isinstance(callee.value, ast.Name) and callee.value.id in {"self", "cls"}:
                    if callee.attr in methods:
                        callees.add(callee.attr)
                        pending.append(methods[callee.attr])
                    else:
                        _require(callee.attr in inherited, refusal, "unknown self/cls test callee")
        _require(
            callees == set(row["sameClassCallees"]),
            refusal,
            "same-class test helper closure differs from reviewed roster",
        )
        required = {row["method"], *callees, *fixtures, *referenced_module}
        _require(
            "FULL" in selected_ranges[path] or required <= selected_ranges[path],
            refusal,
            "referenced local test helper or fixture was not fully exposed",
        )
        for alias, identity in imported.items():
            pinned = row["importedCalls"].get(alias)
            _require(
                pinned is None or pinned == identity,
                refusal,
                "imported test helper identity differs from reviewed roster",
            )
            if identity.startswith("agent_lifecycle.") or identity.startswith("tests."):
                imported_repo[path + ":" + alias] = identity
        local_helpers[row["class"] + "." + row["method"]] = sorted(required)


def _r69h_check_test_dependency_closure(
    root: Path, oracle: dict[str, Any], checked: list[dict[str, Any]]
) -> dict[str, Any]:
    """Bind selected test bodies to their local fixtures, helpers and imports."""
    refusal = "codex-exact-source-exposure-tests"
    relative = "tasks/release-2-16/TEST-DEPENDENCY-ROSTER-v1.json"
    raw_roster = read_authority_bytes(root / relative, root=root, max_bytes=32768)
    _require(
        _sha(raw_roster) == oracle["testDependencyRosterSha256"],
        refusal,
        "test dependency roster differs from reviewed oracle",
    )
    roster = json.loads(raw_roster)
    _require(
        roster.get("schemaVersion") == "alk-r69h-test-dependency-roster.v1"
        and isinstance(roster.get("methods"), list)
        and (len(roster["methods"]) == 16),
        refusal,
        "test dependency roster malformed",
    )
    by_path: dict[str, list[dict[str, Any]]] = {}
    for row in roster["methods"]:
        _require(
            row.get("contentRole") in {"SELECTED", "FULL"}
            and isinstance(row.get("classFixtures"), list)
            and isinstance(row.get("sameClassCallees"), list)
            and isinstance(row.get("importedCalls"), dict)
            and (row.get("unresolvedSelfCalls") == []),
            refusal,
            "test dependency row malformed",
        )
        by_path.setdefault(row["path"], []).append(row)
    expected_paths = {
        "tests/adapter_sessions/test_codex_exact_prompt.py",
        "tests/adapter_sessions/test_process_cleanup.py",
    }
    _require(
        set(by_path) == expected_paths
        and len(by_path["tests/adapter_sessions/test_codex_exact_prompt.py"]) == 7
        and (len(by_path["tests/adapter_sessions/test_process_cleanup.py"]) == 9),
        refusal,
        "selected test method membership differs",
    )
    selected = {
        row["class"] + "." + row["method"] for row in by_path["tests/adapter_sessions/test_codex_exact_prompt.py"]
    }
    c35 = {row["class"] + "." + row["method"] for row in by_path["tests/adapter_sessions/test_process_cleanup.py"]}
    c34_roster = {
        case
        for item in oracle["caseRoster"]["C34"]
        if item["modulePath"] == "tests/adapter_sessions/test_codex_exact_prompt.py"
        for case in item["caseIds"]
    }
    c35_roster = {case for item in oracle["caseRoster"]["C35"] for case in item["caseIds"]}
    _require(selected <= c34_roster and c35 == c35_roster, refusal, "test dependency cases differ from command roster")
    selected_ranges = {row["path"]: {item["symbol"] for item in row["ranges"]} for row in checked}
    fixture_names = {"setUp", "tearDown", "setUpClass", "tearDownClass", "asyncSetUp", "asyncTearDown"}
    inherited = set(dir(unittest.TestCase))
    imported_repo: dict[str, str] = {}
    local_helpers: dict[str, list[str]] = {}
    for path, rows in by_path.items():
        _r69h_check_one_test_dependency(
            root, path, rows, refusal, selected_ranges, fixture_names, inherited, imported_repo, local_helpers
        )
    return {
        "rosterSha256": _sha(raw_roster),
        "selectedMethods": len(roster["methods"]),
        "localHelpers": local_helpers,
        "importedRepoIdentityOnly": imported_repo,
    }


def _single_turn_projection(
    response: dict[str, Any],
    *,
    thread_id: str,
    turn_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Bind one completed, tool-free App Server turn to exact input text elements."""
    thread = response.get("thread") if isinstance(response, dict) else None
    turns = thread.get("turns") if isinstance(thread, dict) else None
    _require(
        isinstance(thread, dict)
        and thread.get("id") == thread_id
        and isinstance(turns, list)
        and len(turns) == 1
        and isinstance(turns[0], dict)
        and turns[0].get("id") == turn_id
        and turns[0].get("status") == "completed"
        and isinstance(turns[0].get("items"), list),
        "codex-exact-bootstrap-review-stale",
        "one completed assigned turn is required",
    )
    thread = _validated_cast(dict[str, Any], thread)
    turns = _validated_cast(list[Any], turns)
    items = turns[0]["items"]
    _require(
        2 <= len(items) <= 64
        and all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] for item in items)
        and len({item["id"] for item in items}) == len(items)
        and items[0].get("type") == "userMessage"
        and all(item.get("type") == "reasoning" for item in items[1:-1])
        and items[-1].get("type") == "agentMessage"
        and items[-1].get("phase") in ("final_answer", None)
        and isinstance(items[-1].get("text"), str),
        "codex-exact-bootstrap-review-stale",
        "unexpected input, output or tool item",
    )
    expected = request.get("params", {}).get("input") if isinstance(request, dict) else None
    observed = items[0].get("content")
    _require(
        isinstance(expected, list) and isinstance(observed, list) and len(expected) == len(observed) and bool(expected),
        "codex-exact-bootstrap-review-stale",
        "input element count differs",
    )
    expected = _validated_cast(list[Any], expected)
    observed = _validated_cast(list[Any], observed)
    for sent, seen in zip(expected, observed, strict=False):
        _require(
            isinstance(sent, dict)
            and isinstance(seen, dict)
            and sent.get("type") == seen.get("type") == "text"
            and isinstance(sent.get("text"), str)
            and isinstance(seen.get("text"), str)
            and sent["text"].encode("utf-8") == seen["text"].encode("utf-8")
            and set(seen) <= {"type", "text", "text_elements"},
            "codex-exact-bootstrap-review-stale",
            "completed input text differs",
        )
        seen = _validated_cast(dict[str, Any], seen)
        sent = _validated_cast(dict[str, Any], sent)
    sequence = [{"id": item["id"], "type": item["type"], "sha256": _sha(canonical_bytes(item))} for item in items]
    return {
        "threadId": thread_id,
        "turnId": turn_id,
        "inputItemId": items[0]["id"],
        "bodyItemId": items[-1]["id"],
        "inputTextSha256": _sha(canonical_bytes(expected)),
        "bodyText": items[-1]["text"],
        "items": sequence,
    }


_FINDING_LINE = re.compile(
    r"- \[(P[123])\] ([A-Za-z0-9][A-Za-z0-9._-]*) \| "
    r"([^\s|:]+):([1-9][0-9]*) \| ([^\r\n]+)\Z"
)


def _review_findings_match_v4(body: dict[str, Any]) -> bool:
    """Map every reviewer-authored v4 text span to one OPEN finding."""
    if body.get("coverageComplete") is not True:
        return False
    raw = body.get("reviewText")
    findings = body.get("findings")
    if not isinstance(raw, str) or not isinstance(findings, list) or len(raw.encode("utf-8")) > 32768:
        return False
    if body.get("verdict") == "PASS":
        return raw in {"NO_CURRENT_FINDINGS", "NO_CURRENT_FINDINGS\n"} and findings == []
    if body.get("verdict") != "FAIL" or not findings:
        return False
    lines = raw.rstrip("\n").split("\n")
    if raw.endswith("\n\n") or len(lines) != len(findings) or len(lines) != len(set(lines)):
        return False
    for ordinal, (line, finding) in enumerate(zip(lines, findings, strict=False), 1):
        match = _FINDING_LINE.fullmatch(line)
        if match is None or not isinstance(finding, dict):
            return False
        level, ident, path, line_no, evidence = match.groups()
        if (
            finding.get("rawSpan") != line
            or finding.get("spanOrdinal") != ordinal
            or finding.get("id") != ident
            or finding.get("reviewLevel") != level
            or finding.get("severity") != {"P1": "HIGH", "P2": "MEDIUM", "P3": "LOW"}[level]
            or finding.get("status") != "OPEN"
            or finding.get("sourcePath") != path
            or finding.get("sourceLine") != int(line_no)
            or finding.get("evidence") != evidence
        ):
            return False
    return True


def _r69h_expand_test_support(
    block: dict[str, Any],
    command_id: str,
    execution: dict[str, Any],
    discovery: dict[str, Any],
    stdout: bytes,
    stderr: bytes,
    oracle: dict[str, Any],
) -> None:
    """Resolve both fixed roster references against complete private receipts."""
    import base64
    import binascii

    refusal = "codex-exact-bootstrap-support-invalid"
    _require(
        isinstance(block, dict)
        and set(block) == set(oracle["testBlockRequiredFields"])
        and block.get("schemaVersion") == "alk-bootstrap-test-support-shared-roster.v1"
        and block.get("commandId") == command_id,
        refusal,
        "shared-roster block or command differs",
    )
    block = _validated_cast(dict[str, Any], block)
    roster = block.get("caseRoster")
    _require(
        isinstance(roster, list)
        and bool(roster)
        and all(isinstance(name, str) and bool(name) for name in roster)
        and roster == sorted(set(roster))
        and block.get("caseRosterSha256") == _sha(canonical_bytes(roster)),
        refusal,
        "case roster or digest differs",
    )
    roster = _validated_cast(list[Any], roster)
    projected_execution = block.get("executionReceipt")
    projected_discovery = block.get("loaderDiscoveryReceipt")
    _require(
        isinstance(projected_execution, dict)
        and isinstance(projected_discovery, dict)
        and projected_execution.get("testNamesRef") == "caseRoster"
        and projected_discovery.get("discoveredCaseIdsRef") == "caseRoster"
        and "testNames" not in projected_execution
        and "discoveredCaseIds" not in projected_discovery,
        refusal,
        "roster references are absent or changed",
    )
    projected_discovery = _validated_cast(dict[str, Any], projected_discovery)
    projected_execution = _validated_cast(dict[str, Any], projected_execution)
    projected_discovery = _validated_cast(dict, projected_discovery)
    expanded_execution = {key: value for key, value in projected_execution.items() if key != "testNamesRef"}
    expanded_discovery = {key: value for key, value in projected_discovery.items() if key != "discoveredCaseIdsRef"}
    expanded_execution["testNames"] = roster
    expanded_discovery["discoveredCaseIds"] = roster
    _require(
        canonical_bytes(expanded_execution) == canonical_bytes(execution)
        and canonical_bytes(expanded_discovery) == canonical_bytes(discovery),
        refusal,
        "expanded receipts differ from complete private receipts",
    )
    try:
        decoded_stdout = base64.b64decode(block["stdoutRawBase64"], validate=True)
        decoded_stderr = base64.b64decode(block["stderrRawBase64"], validate=True)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise LifecycleError(refusal, "raw output encoding is invalid") from exc
    _require(
        decoded_stdout == stdout
        and decoded_stderr == stderr
        and execution.get("stdoutSha256") == _sha(stdout)
        and execution.get("stderrSha256") == _sha(stderr),
        refusal,
        "raw output or digest differs",
    )


def _r69h_project_test_support(
    command_id: str,
    execution: dict[str, Any],
    discovery: dict[str, Any],
    stdout: bytes,
    stderr: bytes,
    oracle: dict[str, Any],
) -> dict[str, Any]:
    """Project one exact private test pair into a single shared-roster block."""
    import base64

    refusal = "codex-exact-bootstrap-support-invalid"
    _require(
        command_id in ("C34", "C35")
        and isinstance(execution, dict)
        and isinstance(discovery, dict)
        and isinstance(stdout, bytes)
        and isinstance(stderr, bytes),
        refusal,
        "test support is malformed",
    )
    discovery = _validated_cast(dict[str, Any], discovery)
    execution = _validated_cast(dict[str, Any], execution)
    stdout = _validated_cast(bytes, stdout)
    execution = _validated_cast(dict, execution)
    discovery = _validated_cast(dict, discovery)
    stderr = _validated_cast(bytes, stderr)
    rule = oracle["testBlocks"][command_id]
    roster = execution.get("testNames")
    expected_paths = {module.replace(".", "/") + ".py" for module in rule["modules"]}
    _require(
        isinstance(roster, list)
        and bool(roster)
        and all(isinstance(name, str) and bool(name) for name in roster)
        and roster == sorted(set(roster))
        and discovery.get("discoveredCaseIds") == roster
        and discovery.get("discoveredCaseCount") == len(roster)
        and discovery.get("moduleNames") == rule["modules"]
        and discovery.get("discoveryMethod") == "unittest.TestLoader.loadTestsFromNames"
        and set(oracle["executionReceiptRequiredFields"]) <= set(execution)
        and set(oracle["loaderDiscoveryRequiredFields"]) <= set(discovery)
        and set(discovery.get("sourceFileSha256", {})) == expected_paths
        and discovery.get("sourceFileSha256") == execution.get("sourceTestFileSha256")
        and discovery.get("sourceBeforeSha256") == discovery.get("sourceFileSha256")
        and discovery.get("sourceAfterSha256") == discovery.get("sourceFileSha256"),
        refusal,
        "execution and separate loader discovery differ",
    )
    roster = _validated_cast(list[Any], roster)
    baseline = set(rule["baselineCaseIds"])
    additions = set(roster) - baseline
    _require(
        baseline <= set(roster)
        and all(
            name.rsplit(".", 1)[-1].startswith("test_r69h_")
            and any(name.startswith(module + ".") for module in rule["modules"])
            for name in additions
        ),
        refusal,
        "case roster exceeds reviewed baseline",
    )
    try:
        started = datetime.fromisoformat(discovery["discoveryStartedAtUtc"])
        ended = datetime.fromisoformat(discovery["discoveryEndedAtUtc"])
        execution_ended = datetime.fromisoformat(execution["endedAtUtc"])
        times_ok = (
            started.tzinfo is not None
            and ended.tzinfo is not None
            and execution_ended.tzinfo is not None
            and execution_ended < started <= ended
        )
    except (KeyError, TypeError, ValueError):
        times_ok = False
    _require(times_ok, refusal, "loader discovery is not separately timed after execution")
    quiet_result = re.search(rb"Ran ([0-9]+) tests? in .*\n\nOK\s*\Z", stderr, re.S)
    _require(
        execution.get("exitCode") == 0
        and quiet_result is not None
        and int(quiet_result.group(1)) == len(roster)
        and b"skipped=" not in stderr
        and b"expected failures=" not in stderr,
        refusal,
        "quiet suite result is incomplete",
    )
    projected_execution = {key: value for key, value in execution.items() if key != "testNames"}
    projected_discovery = {key: value for key, value in discovery.items() if key != "discoveredCaseIds"}
    projected_execution["testNamesRef"] = "caseRoster"
    projected_discovery["discoveredCaseIdsRef"] = "caseRoster"
    block = {
        "schemaVersion": "alk-bootstrap-test-support-shared-roster.v1",
        "commandId": command_id,
        "caseRoster": roster,
        "caseRosterSha256": _sha(canonical_bytes(roster)),
        "executionReceipt": projected_execution,
        "loaderDiscoveryReceipt": projected_discovery,
        "stdoutRawBase64": base64.b64encode(stdout).decode("ascii"),
        "stderrRawBase64": base64.b64encode(stderr).decode("ascii"),
    }
    _r69h_expand_test_support(block, command_id, execution, discovery, stdout, stderr, oracle)
    return block


def _r69h_validation_command_evidence(root, command, raw, mapped_cases, outputs):
    ident = command["id"].lower()
    try:
        result = json.loads(raw[f"{ident}-result.json"])
        cases = json.loads(raw[f"{ident}-cases.json"])
        execution = json.loads(raw[f"{ident}-execution.json"])
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-bootstrap-subject-invalid", "validation support is malformed") from exc
    parts = shlex.split(command["command"])
    _require(
        parts[:3] == ["PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=src", "python3"]
        and parts[3:5] == ["-m", "unittest"]
        and (parts[-1] == "-q")
        and (len(parts) >= 7)
        and (canonical_digest(command["command"]) == command["canonicalDigest"]),
        "codex-exact-bootstrap-subject-invalid",
        "locked validation command is invalid",
    )
    modules = parts[5:-1]
    source_names, source_hashes = _source_test_ids(root, modules)
    python_value = execution.get("pythonResolvedPath") if isinstance(execution, dict) else None
    python_path = Path(python_value) if isinstance(python_value, str) else Path()
    try:
        python_ok = (
            python_path.is_absolute()
            and python_path.resolve(strict=True) == python_path
            and (_file_sha(python_path) == execution.get("pythonSha256"))
        )
    except (OSError, LifecycleError):
        python_ok = False
    try:
        started_at = datetime.fromisoformat(execution["startedAtUtc"])
        ended_at = datetime.fromisoformat(execution["endedAtUtc"])
        time_ok = started_at.tzinfo is not None and ended_at.tzinfo is not None and (started_at <= ended_at)
    except (KeyError, TypeError, ValueError):
        time_ok = False
    stderr = raw[f"{ident}.stderr"]
    count = re.search(b"Ran ([0-9]+) tests? in .*\\n\\nOK\\s*\\Z", stderr, re.S)
    mapping = cases.get("localCaseMapping") if isinstance(cases, dict) else None
    _require(
        isinstance(result, dict)
        and isinstance(cases, dict)
        and isinstance(execution, dict)
        and (count is not None)
        and (result.get(ident) == f"PASS_{int(count.group(1))}_TESTS")
        and (result.get(f"{ident}StderrSha256") == _sha(stderr))
        and (cases.get("commandId") == command["id"])
        and (cases.get("testNames") == source_names)
        and (cases.get("sourceTestFileSha256") == source_hashes)
        and (len(source_names) == int(count.group(1)))
        and isinstance(mapping, dict)
        and all(
            isinstance(group, list) and bool(group) and (set(group) <= set(source_names)) for group in mapping.values()
        )
        and (execution.get("source") == "SUBPROCESS_CAPTURE")
        and (execution.get("contractCommand") == command["command"])
        and (execution.get("commandDigest") == command["canonicalDigest"])
        and (execution.get("argv") == parts[2:])
        and (execution.get("environment") == {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "src"})
        and (execution.get("cwd") == str(root))
        and (execution.get("exitCode") == 0)
        and (execution.get("stdoutSha256") == _sha(raw[f"{ident}.stdout"]))
        and (execution.get("stderrSha256") == _sha(stderr))
        and (execution.get("testNames") == source_names)
        and (execution.get("sourceTestFileSha256") == source_hashes)
        and (type(execution.get("processId")) is int)
        and (execution["processId"] > 0)
        and time_ok
        and python_ok,
        "codex-exact-bootstrap-subject-stale",
        "validation command, output or case provenance differs",
    )
    cases = _validated_cast(dict[str, Any], cases)
    execution = _validated_cast(dict[str, Any], execution)
    mapping = _validated_cast(dict[str, Any], mapping)
    result = _validated_cast(dict[str, Any], result)
    mapped_cases.update(mapping)
    outputs.append(
        {
            "commandDigest": command["canonicalDigest"],
            "outputSha256": canonical_digest(
                {"stdoutSha256": _sha(raw[f"{ident}.stdout"]), "stderrSha256": _sha(stderr)}
            ),
            "caseDigest": canonical_digest(cases),
        }
    )


def _r69h_subject_git(*args: str, allow_missing: bool = False, root: Path) -> bytes | None:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("codex-exact-bootstrap-subject-unavailable", "Git source could not be reopened") from exc
    _require(
        len(result.stdout) <= 4194304 and len(result.stderr) <= 65536,
        "codex-exact-bootstrap-subject-unavailable",
        "Git source exceeds bound",
    )
    if allow_missing and result.returncode != 0:
        return None
    _require(result.returncode == 0, "codex-exact-bootstrap-subject-unavailable", "Git source read failed")
    return result.stdout


def _verify_bootstrap_support_and_cost(
    root: Path, contract: dict, raw: dict[str, bytes], admission: dict, cost: dict, subject: dict
) -> None:
    outputs: list[dict[str, Any]] = []
    mapped_cases: set[str] = set()
    for command in contract["validation"]["commands"]:
        _r69h_validation_command_evidence(root, command, raw, mapped_cases, outputs)
    _require(
        mapped_cases == {case["id"] for case in contract["validation"]["cases"]},
        "codex-exact-bootstrap-subject-stale",
        "PRE case mapping is incomplete",
    )
    _require(
        subject["C34C35CommandOutputCaseDigests"] == outputs,
        "codex-exact-bootstrap-subject-stale",
        "C34/C35 reviewed support differs",
    )
    _require(
        admission.get("status") == "ADMITTED_PREAPPROVED_BY_USER"
        and admission.get("bootstrapAdmissionId") == subject["bootstrapAdmissionId"]
        and (admission.get("implementationOriginAdmissionId") == cost.get("implementationOriginAdmissionId"))
        and (admission.get("implementationOriginAdmissionId") == "r166-pre-ws01-route-bootstrap")
        and (type(admission.get("priorUnknownHolds")) is int)
        and (type(admission.get("tokenCap")) is int)
        and (admission["priorUnknownHolds"] >= 0)
        and (0 < admission["tokenCap"] <= contract["accounting"]["totalModelTokensCap"])
        and (
            admission["priorUnknownHolds"] + admission["tokenCap"]
            == admission.get("admittedUnknownHolds")
            == cost.get("heldUnknownTokens")
        )
        and (cost.get("priorUnknownHolds") == admission["priorUnknownHolds"])
        and (cost.get("windowCap") == admission["tokenCap"])
        and (cost.get("admissionSha256") == _sha(raw["admission.json"]))
        and (admission.get("actualModelTokens") is None)
        and (admission.get("costStatus") == "UNAVAILABLE"),
        "codex-exact-bootstrap-subject-stale",
        "admitted cost source or arithmetic differs",
    )
    _require(
        subject["privateSupportReceiptDigests"] == {name: _sha(value) for name, value in raw.items()}
        and cost.get("costStatus") == subject["costStatus"]
        and (cost.get("heldUnknownTokens") == subject["heldUnknownTokens"])
        and (cost.get("actualModelTokens") is None),
        "codex-exact-bootstrap-subject-stale",
        "private support or held cost differs",
    )
    _require(
        subject["reviewedInputDigest"]
        == canonical_digest({key: value for key, value in subject.items() if key != "reviewedInputDigest"}),
        "codex-exact-bootstrap-subject-stale",
        "reviewed input digest is not source-derived",
    )


def _recompute_bootstrap_subject(root: Path, base: Path, contract: dict[str, Any], subject: dict[str, Any]) -> None:
    """Reopen the private PRE subject; a matching reviewer JSON is insufficient."""
    support = base / "support"
    names = (
        "before-wip-inventory.json",
        "after-wip-inventory.json",
        "c34.stdout",
        "c34.stderr",
        "c34-result.json",
        "c34-cases.json",
        "c34-execution.json",
        "c35.stdout",
        "c35.stderr",
        "c35-result.json",
        "c35-cases.json",
        "c35-execution.json",
        "cost.json",
        "admission.json",
    )
    raw = {name: _read_private(support / name, root=root) for name in names}
    try:
        before = json.loads(raw["before-wip-inventory.json"])
        after = json.loads(raw["after-wip-inventory.json"])
        cost = json.loads(raw["cost.json"])
        admission = json.loads(raw["admission.json"])
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-bootstrap-subject-invalid", "bootstrap support is malformed") from exc
    _require(
        isinstance(before, dict) and isinstance(after, dict) and isinstance(cost, dict) and isinstance(admission, dict),
        "codex-exact-bootstrap-subject-invalid",
        "bootstrap support is incomplete",
    )
    admission = _validated_cast(dict[str, Any], admission)
    after = _validated_cast(dict[str, Any], after)
    before = _validated_cast(dict[str, Any], before)
    cost = _validated_cast(dict[str, Any], cost)
    for inventory in (before, after):
        _require(
            isinstance(inventory.get("inventorySubject"), dict)
            and inventory.get("canonicalInventorySubjectSha256") == canonical_digest(inventory["inventorySubject"]),
            "codex-exact-bootstrap-subject-invalid",
            "WIP inventory digest differs",
        )
    b, a = (before["inventorySubject"], after["inventorySubject"])
    _require(
        subject["wholeWipBeforeAfterInventoryDigest"]
        == {"before": before["canonicalInventorySubjectSha256"], "after": after["canonicalInventorySubjectSha256"]},
        "codex-exact-bootstrap-subject-stale",
        "reviewed WIP inventory differs",
    )

    head = _r69h_subject_git("rev-parse", "HEAD", root=root)
    _require(
        isinstance(head, bytes) and head.decode("ascii").strip() == a.get("gitHead") == b.get("gitHead"),
        "codex-exact-bootstrap-subject-stale",
        "WIP HEAD changed",
    )
    head = _validated_cast(bytes, head)
    diff = _r69h_subject_git("diff", "--binary", "--", "src", "tests", "policy", "tools", root=root)
    _require(
        isinstance(diff, bytes)
        and a.get("trackedDiff", {}).get("sha256") == _sha(diff)
        and (a["trackedDiff"].get("bytes") == len(diff)),
        "codex-exact-bootstrap-subject-stale",
        "tracked WIP diff changed",
    )
    diff = _validated_cast(bytes, diff)
    rows = a.get("trackedModified", []) + a.get("untracked", [])
    before_rows = b.get("trackedModified", []) + b.get("untracked", [])
    _require(
        isinstance(rows, list)
        and isinstance(before_rows, list)
        and (0 < len(rows) <= 512)
        and (len(rows) == len(before_rows))
        and all(isinstance(row, dict) and isinstance(row.get("path"), str) for row in rows + before_rows),
        "codex-exact-bootstrap-subject-invalid",
        "WIP path inventory is invalid",
    )
    before_rows = _validated_cast(list[Any], before_rows)
    rows = _validated_cast(list[Any], rows)
    current = {row["path"]: row for row in rows}
    prior = {row["path"]: row for row in before_rows}
    _require(
        len(current) == len(rows) and len(prior) == len(before_rows) and (set(current) == set(prior)),
        "codex-exact-bootstrap-subject-stale",
        "WIP path set changed",
    )
    status = _r69h_subject_git("status", "--porcelain=v1", "-uall", "--", "src", "tests", "policy", "tools", root=root)
    _require(
        isinstance(status, bytes) and {line[3:].decode("utf-8") for line in status.splitlines()} == set(current),
        "codex-exact-bootstrap-subject-stale",
        "WIP status has an unreviewed path",
    )
    status = _validated_cast(bytes, status)
    owned = set(contract["ownership"]["temporaryLeadWritePaths"])
    for relative, row in current.items():
        path = Path(relative)
        _require(
            not path.is_absolute()
            and ".." not in path.parts
            and (path.parts[0] in {"src", "tests", "policy", "tools"}),
            "codex-exact-bootstrap-subject-invalid",
            "WIP path escapes the checkout",
        )
        target = root / path
        info = target.lstat()
        _require(
            stat.S_ISREG(info.st_mode)
            and info.st_size <= 8388608
            and (row.get("currentBytes") == info.st_size)
            and (row.get("currentSha256") == _file_sha(target)),
            "codex-exact-bootstrap-subject-stale",
            "reviewed WIP bytes changed",
        )
        if relative not in owned:
            _require(
                row.get("currentSha256") == prior[relative].get("currentSha256")
                and row.get("currentBytes") == prior[relative].get("currentBytes"),
                "codex-exact-bootstrap-subject-scope",
                "non-owned WIP changed",
            )
    six = {}
    for relative in contract["ownership"]["temporaryLeadWritePaths"]:
        _require(relative in current, "codex-exact-bootstrap-subject-scope", "temporary owned path is missing")
        head_bytes = _r69h_subject_git("show", f"HEAD:{relative}", allow_missing=True, root=root)
        six[relative] = {
            "beforeExists": head_bytes is not None,
            "beforeSha256": _sha(head_bytes) if head_bytes is not None else None,
            "afterSha256": current[relative]["currentSha256"],
        }
    _require(
        subject["sixPathBeforeAfterSha256"] == six,
        "codex-exact-bootstrap-subject-stale",
        "six owned source bases/afters differ",
    )
    _verify_bootstrap_support_and_cost(root, contract, raw, admission, cost, subject)
