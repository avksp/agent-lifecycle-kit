"""Validate Ed25519 compatibility, strict decoding and the optimized hot path."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import statistics
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.canonical import write_json_replace_private

SCHEMA = "agent-ed25519-equivalence-validation.v1"
MIN_SAMPLES = 7


def validate_ed25519_equivalence(*, module_path: Path, vectors_path: Path, reference_path: Path) -> dict[str, Any]:
    """Run bounded compatibility and interleaved differential checks."""

    module = _load_module(module_path, "agent_lifecycle_ed25519_candidate")
    reference = _load_module(reference_path, "agent_lifecycle_ed25519_reference")
    fixture = json.loads(vectors_path.read_text(encoding="utf-8"))
    vectors = fixture.get("vectors") if isinstance(fixture, dict) else None
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    vector_count = len(vectors) if isinstance(vectors, list) else 0
    vector_results = []
    if not isinstance(vectors, list) or not vectors:
        blockers.append({"code": "ed25519-vectors-missing"})
    else:
        for vector in vectors:
            result = _check_vector(module, reference, vector)
            vector_results.append(result)
            if result["status"] != "PASS":
                blockers.append({"code": "ed25519-vector-mismatch", "vectorId": result.get("vectorId")})
        checks.append({"id": "rfc8032-and-differential-vectors", "status": "PASS" if not blockers else "FAIL", "count": vector_count})

    malformed = _malformed_checks(module)
    checks.append({"id": "strict-malformed-inputs", "status": "PASS" if malformed else "FAIL"})
    if not malformed:
        blockers.append({"code": "ed25519-malformed-input-accepted"})

    source = module_path.read_text(encoding="utf-8")
    ast_checks = _ast_checks(source)
    checks.append({"id": "iterative-projective-scalar-multiplication", "status": "PASS" if ast_checks["status"] == "PASS" else "FAIL"})
    if ast_checks["status"] != "PASS":
        blockers.append({"code": "ed25519-hot-path-shape-invalid", "details": ast_checks})

    benchmark = _benchmark(module, reference)
    checks.append({"id": "interleaved-median-ratio", "status": benchmark["status"]})
    if benchmark["status"] != "PASS":
        blockers.append({"code": "ed25519-performance-ratio-exceeded", "details": benchmark["operations"]})

    body = {
        "schemaVersion": SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "module": {"path": module_path.name, "sha256": _sha256(module_path.read_bytes())},
        "reference": {"path": reference_path.name, "sha256": _sha256(reference_path.read_bytes())},
        "vectors": vector_results,
        "checks": checks,
        "ast": ast_checks,
        "benchmark": benchmark,
        "limits": {"minimumInterleavedSamples": MIN_SAMPLES, "maxOptimizedToReferenceMedianRatioBps": 2_000},
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _check_vector(module: ModuleType, reference: ModuleType, vector: Any) -> dict[str, Any]:
    if not isinstance(vector, dict):
        return {"status": "FAIL", "vectorId": None, "reason": "not-object"}
    vector_id = vector.get("id")
    try:
        seed = bytes.fromhex(str(vector["seed"]))
        message = bytes.fromhex(str(vector["message"]))
        expected_public = bytes.fromhex(str(vector["publicKey"]))
        expected_signature = bytes.fromhex(str(vector["signature"]))
        candidate_public = module.publickey_from_seed(seed)
        candidate_signature = module.sign(seed, message)
        reference_public = reference.publickey_from_seed(seed)
        reference_signature = reference.sign(seed, message)
        ok = (
            candidate_public == expected_public == reference_public
            and candidate_signature == expected_signature == reference_signature
            and module.verify(candidate_public, message, candidate_signature)
        )
        return {"status": "PASS" if ok else "FAIL", "vectorId": vector_id}
    except (KeyError, TypeError, ValueError) as exc:
        return {"status": "FAIL", "vectorId": vector_id, "errorType": type(exc).__name__}


def _malformed_checks(module: ModuleType) -> bool:
    seed = bytes(range(32))
    public_key = module.publickey_from_seed(seed)
    signature = module.sign(seed, b"malformed")
    return all(
        (
            not module.verify(public_key, b"malformed", signature[:-1] + bytes([signature[-1] ^ 1])),
            not module.verify(module.P.to_bytes(32, "little"), b"", signature),
            not module.verify(public_key, b"", bytes(32) + module.Q.to_bytes(32, "little")),
            _raises_value_error(module, bytes([1]) + bytes(30) + bytes([0x80])),
        )
    )


def _raises_value_error(module: ModuleType, encoded: bytes) -> bool:
    try:
        module._decode_point(encoded)
    except ValueError:
        return True
    return False


def _ast_checks(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    scalar = next((node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_scalar_mult"), None)
    encode = next((node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_encode_point"), None)
    if scalar is None or encode is None:
        return {"status": "FAIL", "reason": "required-functions-missing"}
    scalar_calls_pow = sum(
        1
        for node in ast.walk(scalar)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "pow"
    )
    has_loop = any(isinstance(node, (ast.While, ast.For)) for node in ast.walk(scalar))
    has_recursive_call = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_scalar_mult"
        for node in ast.walk(scalar)
    )
    encode_pow_count = sum(
        1
        for node in ast.walk(encode)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "pow"
    )
    status = "PASS" if has_loop and scalar_calls_pow == 0 and not has_recursive_call and encode_pow_count == 1 else "FAIL"
    return {
        "status": status,
        "scalarHasLoop": has_loop,
        "scalarPowCalls": scalar_calls_pow,
        "scalarRecursiveCalls": int(has_recursive_call),
        "encodeFinalPowCalls": encode_pow_count,
        "constantTimeClaim": False,
    }


def _benchmark(module: ModuleType, reference: ModuleType) -> dict[str, Any]:
    seed = bytes(range(32))
    message = b"release-1-78-ed25519-benchmark"
    public_key = module.publickey_from_seed(seed)
    reference_public = reference.publickey_from_seed(seed)
    signature = module.sign(seed, message)
    reference_signature = reference.sign(seed, message)
    operations: dict[str, dict[str, Any]] = {}
    calls: dict[str, tuple[Callable[[], Any], Callable[[], Any]]] = {
        "publickey": (lambda: module.publickey_from_seed(seed), lambda: reference.publickey_from_seed(seed)),
        "sign": (lambda: module.sign(seed, message), lambda: reference.sign(seed, message)),
        "verify": (lambda: module.verify(public_key, message, signature), lambda: reference.verify(reference_public, message, reference_signature)),
    }
    for name, (candidate_call, reference_call) in calls.items():
        optimized: list[int] = []
        affine: list[int] = []
        for _ in range(MIN_SAMPLES):
            start = time.perf_counter_ns()
            candidate_call()
            optimized.append(time.perf_counter_ns() - start)
            start = time.perf_counter_ns()
            reference_call()
            affine.append(time.perf_counter_ns() - start)
        optimized_median = int(statistics.median(optimized))
        affine_median = int(statistics.median(affine))
        ratio_bps = (optimized_median * 10_000 // affine_median) if affine_median else 10_001
        operations[name] = {
            "samples": MIN_SAMPLES,
            "optimizedMedianNs": optimized_median,
            "referenceMedianNs": affine_median,
            "ratioBps": ratio_bps,
            "status": "PASS" if ratio_bps <= 2_000 else "FAIL",
        }
    return {"status": "PASS" if all(item["status"] == "PASS" for item in operations.values()) else "FAIL", "operations": operations}


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True, type=Path)
    parser.add_argument("--vectors", required=True, type=Path)
    parser.add_argument("--reference", type=Path, default=Path("tests/neutrality/reference_ed25519.py"))
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    payload = validate_ed25519_equivalence(module_path=args.module, vectors_path=args.vectors, reference_path=args.reference)
    write_json_replace_private(args.evidence, payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
