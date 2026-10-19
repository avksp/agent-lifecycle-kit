from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, file_identity, write_json
except ModuleNotFoundError:  # pragma: no cover - supports package-style test imports
    from tools.release.release_common import digest_value, file_identity, write_json

FORBIDDEN_SNIPPETS = (
    "shell=True",
    "os.system(",
    "pty.spawn(",
    "pexpect.",
    ".write_text(",
    ".write_bytes(",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", action="append", default=[])
    parser.add_argument("--launcher")
    parser.add_argument("--profile")
    parser.add_argument("--qualification")
    parser.add_argument("--redaction")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    paths = list(args.paths)
    paths.extend(path for path in (args.launcher, args.profile, args.qualification, args.redaction) if path)
    if not paths:
        parser.error("at least one --paths or named source path is required")
    blockers: list[dict[str, Any]] = []
    scanned: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for file_path in files:
            text = file_path.read_text(encoding="utf-8")
            scanned.append(file_identity(file_path))
            for snippet in FORBIDDEN_SNIPPETS:
                if snippet in text and not _allowed_write(file_path, snippet):
                    blockers.append({"code": "adapter-launcher-forbidden-snippet", "path": file_path.as_posix(), "snippet": snippet})
            blockers.extend(_boundary_blockers(file_path, text))
            blockers.extend(_identity_and_redaction_blockers(file_path, text, args))
    body = {
        "schemaVersion": "agent-adapter-launcher-security-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "scannedFiles": scanned,
        "blockers": blockers,
        "requiredInvariants": {
            "argvArrays": True,
            "shellFalse": True,
            "envAllowlist": True,
            "redactedReceipts": True,
            "nativeConfigWrites": False,
            "secretStorage": False,
            "genericDescriptorLaunch": False,
            "exactEnvironmentNames": True,
            "contentBoundExecutableIdentity": True,
            "sharedRedactionAuthority": True,
        },
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _allowed_write(path: Path, snippet: str) -> bool:
    if path.as_posix().endswith("session_store.py") and snippet in {".write_text(", ".write_bytes("}:
        return True
    return False


def _boundary_blockers(path: Path, text: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [{"code": "adapter-launcher-source-invalid", "path": path.as_posix()}]

    if path.name == "launcher.py":
        if "adapter-generic-launch-disabled" not in text:
            blockers.append({"code": "adapter-generic-launch-blocker-missing", "path": path.as_posix()})
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                if isinstance(child.func, ast.Name) and child.func.id == "run_process":
                    if node.name == "launch_from_local_profile":
                        continue
                    blockers.append(
                        {
                            "code": "adapter-generic-launch-process-route",
                            "path": path.as_posix(),
                            "function": node.name,
                        }
                    )
                elif _is_subprocess_call(child, "run") and not (
                    node.name == "_git_bytes" and _is_bounded_git_read(child)
                ):
                    blockers.append(
                        {
                            "code": "adapter-git-identity-process-route",
                            "path": path.as_posix(),
                            "function": node.name,
                        }
                    )
    blockers.extend(_popen_blockers(path, tree))
    if path.name == "env.py":
        if "import fnmatch" in text or "fnmatch." in text:
            blockers.append({"code": "adapter-env-wildcard-route", "path": path.as_posix()})
        if "adapter-env-wildcard-disallowed" not in text:
            blockers.append({"code": "adapter-env-wildcard-blocker-missing", "path": path.as_posix()})
    return blockers


def _identity_and_redaction_blockers(path: Path, text: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    required_markers: tuple[str, ...] = ()
    category = None
    if args.profile and path.as_posix() == Path(args.profile).as_posix():
        required_markers = ("build_executable_identity", "resolvedPathSha256", "executableContentSha256", "pathStored")
        category = "profile"
    elif args.qualification and path.as_posix() == Path(args.qualification).as_posix():
        required_markers = ("executableIdentity", "shipped_profile_digest", "qualified-launch-executable-identity-mismatch")
        category = "qualification"
    elif args.redaction and path.as_posix() == Path(args.redaction).as_posix():
        required_markers = ("_BARE_TOKEN", "redact_text_with_stats", "LOCAL_PATH_REDACTION")
        category = "redaction"
    elif args.launcher and path.as_posix() == Path(args.launcher).as_posix():
        required_markers = ("host_identity", "verify_plan_package_integrity", "executable-identity-unavailable")
        category = "launcher"
    if category is None:
        return []
    missing = [marker for marker in required_markers if marker not in text]
    return [
        {
            "code": "adapter-launcher-security-marker-missing",
            "path": path.as_posix(),
            "category": category,
            "markers": missing,
        }
    ] if missing else []


def _popen_blockers(path: Path, tree: ast.AST) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and _is_subprocess_call(child, "Popen")
        ]
        for call in calls:
            if path.name == "process.py" and node.name in {"_run_bounded_process", "run_process"} and _is_bounded_popen(call, node):
                continue
            if _is_selector_bounded_popen(call, node, tree):
                continue
            if _is_owned_bounded_popen(call, node, tree, path):
                continue
            blockers.append(
                {
                    "code": "adapter-unbounded-process-route",
                    "path": path.as_posix(),
                    "function": node.name,
                }
            )
    return blockers


def _has_expression(tree: ast.AST, expression: str) -> bool:
    expected = ast.dump(ast.parse(expression, mode="eval").body, include_attributes=False)
    return any(ast.dump(node, include_attributes=False) == expected for node in ast.walk(tree))


def _guarded_expression(tree: ast.AST, expression: str) -> bool:
    return any(isinstance(node, ast.Call) and _is_name(node.func, "_require") and node.args
               and _has_expression(node.args[0], expression) for node in ast.walk(tree))


def _positive_constant(tree: ast.AST, name: str, maximum: int) -> bool:
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and any(_is_name(target, name) for target in node.targets):
            return (isinstance(node.value, ast.Constant) and type(node.value.value) in (int, float)
                    and 0 < node.value.value <= maximum)
    return False


def _guarded_pipe_alias(function: ast.AST, tree: ast.AST, name: str, pipe: str) -> bool:
    """Accept only a no-op typing cast of the already guarded process pipe."""
    if not _guarded_expression(function, f"process.{pipe} is not None"):
        return False
    assignments = [node for node in ast.walk(function) if isinstance(node, ast.Assign)
                   and any(_is_name(target, name) for target in node.targets)]
    if len(assignments) != 1 or len(assignments[0].targets) != 1:
        return False
    value = assignments[0].value
    if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and len(value.args) == 2 and not value.keywords):
        return False
    cast_name = value.func.id
    if any((isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == cast_name)
           or (isinstance(node, ast.arg) and node.arg == cast_name)
           or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == cast_name)
           for node in ast.walk(function)):
        return False
    if not any(isinstance(node, ast.ImportFrom) and node.module == "typing"
               and any(alias.name == "cast" and (alias.asname or alias.name) == cast_name
                       for alias in node.names) for node in getattr(tree, "body", [])):
        return False
    if any(isinstance(node, (ast.Assign, ast.AnnAssign)) and
           any(_is_name(target, cast_name) for target in
               (node.targets if isinstance(node, ast.Assign) else [node.target]))
           for node in getattr(tree, "body", [])):
        return False
    source = value.args[1]
    return (isinstance(source, ast.Attribute) and _is_name(source.value, "process")
            and source.attr == pipe
            and _has_expression(function, f"os.set_blocking({name}.fileno(), False)"))


def _metadata_counter_carry(function: ast.AST, functions: dict[str, ast.FunctionDef]) -> bool:
    name = "_receive_codex_metadata_response"
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call) and _is_name(node.func, name)]
    if not calls:
        return True  # The original inline counter is checked in its own function.
    if name not in functions:
        return False
    assignments = [node for node in ast.walk(function) if isinstance(node, ast.Assign)
                   and isinstance(node.value, ast.Call) and _is_name(node.value.func, name)]
    if len(assignments) != len(calls):
        return False
    for node in assignments:
        if not (len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple)
                and len(node.targets[0].elts) == 2 and _is_name(node.targets[0].elts[1], "total")
                and all(_is_name(_keywords(node.value).get(key), key)
                        for key in ("deadline", "selector", "stdout", "buffered", "total"))):
            return False
    receiver = functions[name]
    returns = [node for node in ast.walk(receiver) if isinstance(node, ast.Return)]
    if not returns or not all(isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2
                              and _is_name(node.value.elts[1], "total") for node in returns):
        return False
    # A fresh zero inside the delegate would silently turn the aggregate cap
    # into a per-response cap. Only the original augmented byte counter remains.
    return not any(isinstance(node, (ast.Assign, ast.AnnAssign)) and
                   any(_is_name(target, "total") for target in
                       (node.targets if isinstance(node, ast.Assign) else [node.target]))
                   for node in ast.walk(receiver))


def _is_selector_bounded_popen(call: ast.Call, function: ast.AST, tree: ast.AST) -> bool:
    keywords = _keywords(call)
    if (len(call.args) != 1 or not isinstance(call.args[0], ast.List)
            or ("shell" in keywords and not _is_false(keywords["shell"]))
            or not isinstance(keywords.get("env"), ast.Name)
            or not _is_subprocess_constant(keywords.get("stdout"), "PIPE")
            or not _is_subprocess_constant(keywords.get("stderr"), "DEVNULL")):
        return False
    functions = {node.name: node for node in getattr(tree, "body", []) if isinstance(node, ast.FunctionDef)}
    flow = _reachable_local_functions(function, functions)
    finalizers = ast.Module(body=[child for node in ast.walk(function)
                                 if isinstance(node, ast.Try) for child in node.finalbody], type_ignores=[])
    if not all(_has_expression(finalizers, expression) for expression in (
        "process.poll()", "process.terminate()", "process.kill()", "process.wait(timeout=2)",
    )) or not _has_expression(flow, "selector.select(max(0.0, deadline - time.monotonic()))"):
        return False
    if _is_subprocess_constant(keywords.get("stdin"), "DEVNULL"):
        return (_has_expression(function, "time.monotonic() + 15.0")
                and _guarded_expression(function, "total <= limit")
                and _has_expression(function, "process.wait(timeout=remaining)")
                and _has_expression(function, "os.read(process.stdout.fileno(), 65536)"))
    return (
        _is_subprocess_constant(keywords.get("stdin"), "PIPE")
        and _positive_constant(tree, "_APP_SERVER_TIMEOUT_SECONDS", 900)
        and _positive_constant(tree, "_APP_SERVER_MAX_REQUEST_BYTES", 1048576)
        and _has_expression(function, "time.monotonic() + _APP_SERVER_TIMEOUT_SECONDS")
        and _guarded_expression(function, "len(raw) <= _APP_SERVER_MAX_REQUEST_BYTES")
        and _guarded_expression(flow, "total <= 4194304")
        and (_has_expression(function, "os.set_blocking(process.stdin.fileno(), False)")
             or _guarded_pipe_alias(function, tree, "stdin", "stdin"))
        and (_has_expression(function, "os.set_blocking(process.stdout.fileno(), False)")
             or _guarded_pipe_alias(function, tree, "stdout", "stdout"))
        and _has_expression(flow, "writer.select(max(0.0, remaining))")
        and _metadata_counter_carry(function, functions)
        and _guarded_expression(function, "_sha(binary.read_bytes()) == expected_binary_sha256")
    )


def _is_owned_bounded_popen(call: ast.Call, function: ast.AST, tree: ast.AST, path: Path) -> bool:
    # Follow the actual local delegates and bounded capture implementation;
    # a filename/function name alone is never an acceptance condition.
    keywords = _keywords(call)
    if (len(call.args) != 1 or not _is_name(call.args[0], "argv")
            or not _is_false(keywords.get("shell")) or not _is_name(keywords.get("env"), "env")
            or not all(_is_subprocess_constant(keywords.get(key), "PIPE") for key in ("stdin", "stdout", "stderr"))):
        return False
    functions = {node.name: node for node in getattr(tree, "body", []) if isinstance(node, ast.FunctionDef)}
    flow = _reachable_local_functions(function, functions)
    required = ("_finish_started_process", "_write_observed_stdin", "_exceptional_started_failure", "_finish_capture")
    if not all(name in functions for name in required):
        return False
    if not all(_has_expression(flow, expression) for expression in (
        "ProcessGroupOwner(process)", "_CaptureState(output_limit)", "deadline_ns / 1000000000",
    )) or not _bounded_ordinary_stdin_delegate(flow, functions, tree):
        return False
    writers = [node for node in ast.walk(flow) if isinstance(node, ast.Call)
               and _is_name(node.func, "_write_observed_stdin")]
    if not writers or not all(_is_name(_keywords(node).get("deadline_monotonic_ns"), "deadline_ns") for node in writers):
        return False
    finisher_calls = [node for node in ast.walk(flow) if isinstance(node, ast.Call)
                      and _is_name(node.func, "_finish_started_process")]
    if not finisher_calls or not all(_is_name(_keywords(node).get("deadline"), "deadline") for node in finisher_calls):
        return False
    checks = {
        "_finish_started_process": ("time.monotonic() >= deadline", "capture.output_limit_exceeded.is_set()",
                                    "owner.terminate(grace_seconds=max(0.05, cleanup_grace_seconds))", "owner.verify()"),
        "_write_observed_stdin": ("os.set_blocking(fd, False)", "time.monotonic() >= deadline",
                                  "os.write(fd, data[count:count + 8192])"),
        "_exceptional_started_failure": ("owner.terminate(grace_seconds=grace)", "process.wait(timeout=grace)"),
        "_finish_capture": ("reader.join(max(0.0, deadline - time.monotonic()))",),
    }
    if not all(_has_expression(functions[name], expression) for name, expressions in checks.items() for expression in expressions):
        return False
    capture_path = path.with_name("process_capture.py")
    try:
        capture = ast.parse(capture_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    return all(_has_expression(capture, expression) for expression in (
        "self.output_limit - self.total_output", "chunk[:remaining]", "len(chunk) > remaining",
        "self.output_limit_exceeded.set()", "stream.read(8192)",
    ))



def _bounded_ordinary_stdin_delegate(
    flow: ast.AST, functions: dict[str, ast.FunctionDef], tree: ast.AST
) -> bool:
    writes = [node for node in ast.walk(flow) if isinstance(node, ast.Call)
              and _is_name(node.func, "_write_stdin")]
    if not writes:
        return True
    helper = functions.get("_write_ordinary_stdin")
    closer = functions.get("_close_exceptional_process_streams")
    failure = functions.get("_observed_failure")
    if helper is None or closer is None or failure is None:
        return False
    local_writes = [node for node in ast.walk(helper) if isinstance(node, ast.Call)
                    and _is_name(node.func, "_write_stdin")]
    if len(writes) != 1 or local_writes != writes:
        return False
    if not _has_expression(helper, "_write_stdin(process, inputs.input_bytes)"):
        return False
    targets = [node for node in ast.walk(helper) if isinstance(node, ast.FunctionDef) and node.name == "write"]
    if len(targets) != 1 or not any(node is writes[0] for node in ast.walk(targets[0])):
        return False
    if any(isinstance(node, ast.Call) and _is_name(node.func, "write") for node in ast.walk(helper)):
        return False
    if any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == "write"
           for node in ast.walk(helper)):
        return False
    writer_assignments = [node for node in ast.walk(helper) if isinstance(node, ast.Name)
                          and isinstance(node.ctx, ast.Store) and node.id == "writer"]
    thread_bindings = [node for node in helper.body if isinstance(node, ast.Assign)
                       and len(node.targets) == 1 and _is_name(node.targets[0], "writer")]
    expected_thread = ast.parse("threading.Thread(target=write, name='alk-process-stdin', daemon=True)", mode="eval").body
    if (len(writer_assignments) != 1 or len(thread_bindings) != 1
            or ast.dump(thread_bindings[0].value, include_attributes=False)
            != ast.dump(expected_thread, include_attributes=False)):
        return False
    finisher = functions.get("_finish_capture")
    if finisher is None:
        return False
    live_guard = [node for node in finisher.body if isinstance(node, ast.If)
                  and ast.dump(node.test, include_attributes=False)
                  == ast.dump(ast.parse("any(reader.is_alive() for reader in readers)", mode="eval").body,
                              include_attributes=False)]
    if len(live_guard) != 1 or len(live_guard[0].body) != 1 or not isinstance(live_guard[0].body[0], ast.Raise):
        return False
    finalizers = [node for node in ast.walk(finisher) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and _is_name(node.func.value, "capture")
                  and node.func.attr == "finish"]
    if (len(finalizers) != 1 or live_guard[0].lineno >= finalizers[0].lineno
            or not _has_expression(finalizers[0], "capture.finish(process, readers, grace_seconds)")):
        return False
    fatal = live_guard[0].body[0]
    if (not isinstance(fatal.exc, ast.Call) or not _is_name(fatal.exc.func, "RuntimeError")
            or live_guard[0].orelse):
        return False
    imported = any(isinstance(node, ast.ImportFrom)
                   and node.module == "agent_lifecycle.adapter_sessions.process_capture"
                   and any(alias.name == "_write_stdin" and alias.asname in (None, "_write_stdin")
                           for alias in node.names) for node in getattr(tree, "body", []))
    if not imported or any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                           and node.id == "_write_stdin" for node in ast.walk(tree)):
        return False
    required = (
        "threading.Thread(target=write, name='alk-process-stdin', daemon=True)",
        "state.readers.append(writer)", "writer.start()", "writer.is_alive()",
        "inputs.cancel_event is not None and inputs.cancel_event.is_set()",
        "deadline - time.monotonic()", "cancelled or remaining <= 0",
        "writer.join(min(0.02, remaining))",
    )
    if not all(_has_expression(helper, expression) for expression in required):
        return False
    retain = [node.lineno for node in helper.body if isinstance(node, ast.Expr)
              and _has_expression(node.value, "state.readers.append(writer)")]
    start = [node.lineno for node in helper.body if isinstance(node, ast.Expr)
             and _has_expression(node.value, "writer.start()")]
    if len(retain) != 1 or len(start) != 1 or retain[0] >= start[0]:
        return False
    if not _has_expression(flow, "on_input is None and inputs.absolute_deadline_monotonic_ns is None"):
        return False
    if not _has_expression(closer,
            "cleanup.get('directChildExited') is not True or "
            "cleanup.get('knownDescendantsGone') is not True or not readers_done"):
        return False
    terminate = [node.lineno for node in ast.walk(failure) if isinstance(node, ast.Call)
                 and _has_expression(node, "owner.terminate(grace_seconds=max(0.05, cleanup_grace_seconds))")]
    join = [node.lineno for node in ast.walk(failure) if isinstance(node, ast.Call)
            and _has_expression(node, "_finish_capture(process, capture, readers, cleanup_grace_seconds)")]
    close = [node.lineno for node in ast.walk(failure) if isinstance(node, ast.Call)
             and _has_expression(node, "process.stdin.close()")]
    return (len(terminate) == len(join) == len(close) == 1
            and terminate[0] < join[0] < close[0])


def _reachable_local_functions(function: ast.AST, functions: dict[str, ast.FunctionDef]) -> ast.Module:
    selected = [function]
    seen: set[str] = set()
    for current in selected:
        for node in ast.walk(current):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                if name in functions and name not in seen:
                    seen.add(name)
                    selected.append(functions[name])
    return ast.Module(body=selected, type_ignores=[])


def _is_bounded_git_read(call: ast.Call) -> bool:
    if len(call.args) != 1 or not isinstance(call.args[0], ast.List):
        return False
    argv = call.args[0].elts
    if len(argv) != 2 or not isinstance(argv[0], ast.Constant) or argv[0].value != "git":
        return False
    if not isinstance(argv[1], ast.Starred) or not isinstance(argv[1].value, ast.Name) or argv[1].value.id != "args":
        return False
    keywords = _keywords(call)
    timeout = keywords.get("timeout")
    return (
        _is_name(keywords.get("cwd"), "root")
        and _is_false(keywords.get("shell"))
        and _is_subprocess_constant(keywords.get("stdin"), "DEVNULL")
        and _is_subprocess_constant(keywords.get("stdout"), "PIPE")
        and _is_subprocess_constant(keywords.get("stderr"), "PIPE")
        and isinstance(timeout, ast.Constant)
        and isinstance(timeout.value, (int, float))
        and 0 < timeout.value <= 10
        and _is_false(keywords.get("check"))
    )


def _is_bounded_popen(call: ast.Call, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if len(call.args) != 1 or not _is_name(call.args[0], "argv"):
        return False
    keywords = _keywords(call)
    safe_call = (
        _is_false(keywords.get("shell"))
        and _is_name(keywords.get("env"), "env")
        and _is_subprocess_constant(keywords.get("stdin"), "PIPE")
        and _is_subprocess_constant(keywords.get("stdout"), "PIPE")
        and _is_subprocess_constant(keywords.get("stderr"), "PIPE")
    )
    referenced_names = {child.id for child in ast.walk(function) if isinstance(child, ast.Name)}
    process_methods = {
        child.func.attr
        for child in ast.walk(function)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id == "process"
    }
    owner_methods = {
        child.func.attr
        for child in ast.walk(function)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id == "owner"
    }
    return (
        safe_call
        and {"max_input_bytes", "max_output_bytes", "timeout_seconds"} <= referenced_names
        and {"poll", "wait"} <= process_methods
        and ({"kill"} <= process_methods or {"terminate", "verify"} <= owner_methods)
    )


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {item.arg: item.value for item in call.keywords if item.arg is not None}


def _is_subprocess_call(call: ast.Call, name: str) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "subprocess"
        and call.func.attr == name
    )


def _is_subprocess_constant(value: ast.expr | None, name: str) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "subprocess"
        and value.attr == name
    )


def _is_name(value: ast.expr | None, name: str) -> bool:
    return isinstance(value, ast.Name) and value.id == name


def _is_false(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and value.value is False


if __name__ == "__main__":
    raise SystemExit(main())
