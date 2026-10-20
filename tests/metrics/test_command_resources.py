"""Real collection and hostile tree mutations, without model calls."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import (
    LifecycleError, canonical_digest, sha256_hex, write_json_create,
)
from agent_lifecycle.contracts.release_accounting_schemas import validate_command_resource_receipt
from agent_lifecycle.metrics.command_resources import (
    CommandMeasurement, collect_command, command_accounting_entries,
    run_measured_command,
)
from agent_lifecycle.metrics.release_accounting import build_release_accounting, validate_release_accounting


def request(root: Path) -> dict:
    source = root / "subject.py"
    if not source.exists():
        source.write_text("answer = 42\n", encoding="utf-8")
    files = {"subject.py": sha256_hex(source.read_bytes())}
    return {
        "schemaVersion": "agent-command-resource-request.v1",
        "operationDigest": "a" * 64, "sourceRevision": "b" * 40,
        "sourceRoot": str(root), "sourceFiles": files,
        "sourceSnapshotDigest": canonical_digest(files), "phase": "controller",
    }


class CommandResourceTests(unittest.TestCase):
    def test_unknown_native_tokens_keep_known_and_zero_phase_totals_partial(self) -> None:
        from agent_lifecycle.metrics.phase_resources import build_phase_resource_measurement

        for input_tokens in (0, 10):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, receipt = collect_command(request(root), ["version"], lambda: 0)
                phase = build_phase_resource_measurement([
                    {"phaseId": "known", "phaseKind": "AUDIT", "durationMs": 0, "steps": 0,
                     "tokens": {"input": input_tokens, "output": 0}},
                ])
                write_json_create(root / "native.json", receipt)
                write_json_create(root / "phase.json", phase)
                report = build_release_accounting("2.21.0", [Path("native.json"), Path("phase.json")], project_root=root)
                self.assertEqual(validate_release_accounting(report)["status"], "PASS")
                self.assertEqual(report["totals"]["metrics"]["tokens"], {"status": "PARTIAL", "value": input_tokens})

    def test_nested_parent_clock_source_and_containment_mutations_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            value = request(Path(tmp))
            _, original = collect_command(
                value, ["workflow"],
                lambda: collect_command({**value, "operationDigest": "c" * 64}, ["version"], lambda: 0)[0],
            )
        for key, value in (("parentSpanDigest", "f" * 64), ("clockDomainDigest", "f" * 64),
                           ("sourceRevision", "f" * 40), ("endWallNs", original["endWallNs"] + 1)):
            with self.subTest(field=key):
                receipt = deepcopy(original)
                child = receipt["children"][0]
                child[key] = value
                child["receiptDigest"] = canonical_digest({k: v for k, v in child.items() if k != "receiptDigest"})
                receipt["receiptDigest"] = canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"})
                self.assertEqual(validate_command_resource_receipt(receipt)["status"], "FAIL")

    def test_unsupported_source_caps_and_incompatible_root_aggregation_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            value = request(Path(tmp))
            _, first = collect_command(value, ["version"], lambda: 0)
            _, second = collect_command({**value, "sourceRevision": "f" * 40}, ["version"], lambda: 0)
            with self.assertRaises(LifecycleError):
                command_accounting_entries([first, second])
            value["sourceFiles"] = {f"source-{index}.py": "c" * 64 for index in range(65)}
            value["sourceSnapshotDigest"] = canonical_digest(value["sourceFiles"])
            with self.assertRaises(LifecycleError):
                collect_command(value, ["version"], lambda: self.fail("must not execute"))

    def test_real_command_failed_exit_and_private_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, receipt = collect_command(request(Path(tmp)), ["version", "private-secret"], lambda: 7)
        self.assertEqual(code, 7)
        self.assertEqual(receipt["outcome"], "FAILED")
        self.assertEqual(validate_command_resource_receipt(receipt)["status"], "PASS")
        self.assertGreaterEqual(receipt["inclusiveCpuNs"], 0)
        self.assertNotIn("private-secret", str(receipt))
        self.assertNotIn(tmp, str(receipt))
        self.assertEqual(receipt["modelTokens"], {"status": "UNAVAILABLE", "value": None})

    def test_nested_spans_use_exclusive_time_and_one_root_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = request(root)
            parent, child = CommandMeasurement(value, ["workflow"]), None
            with patch("agent_lifecycle.metrics.command_resources.time.perf_counter_ns", side_effect=[100, 120, 160, 200]), \
                 patch("agent_lifecycle.metrics.command_resources.time.process_time_ns", side_effect=[10, 15, 20, 30]):
                parent.start()
                child = CommandMeasurement({**value, "operationDigest": "c" * 64}, ["version"])
                child.start()
                nested = child.finish(2)
                receipt = parent.finish(0)
            self.assertEqual(receipt["inclusiveWallNs"], 100)
            self.assertEqual(receipt["exclusiveWallNs"], 60)
            self.assertEqual(receipt["exclusiveCpuNs"], 15)
            entries = command_accounting_entries([receipt])
            self.assertEqual(len(entries), 2)
            self.assertEqual({entry["sourceArtifactDigest"] for entry in entries}, {canonical_digest(receipt)})
            with self.assertRaises(LifecycleError):
                command_accounting_entries([receipt, nested])
            with self.assertRaises(LifecycleError):
                command_accounting_entries([receipt, receipt])

    def test_tree_mutations_refuse_even_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, original = collect_command(request(Path(tmp)), ["version"], lambda: 0)
        mutations = {
            "exclusiveWallNs": original["inclusiveWallNs"] + 1,
            "endCpuNs": 0, "exitCode": True, "sourceRevision": "not-a-revision",
            "childCpu": {"status": "MEASURED", "value": 0},
            "modelTokens": {"status": "MEASURED", "value": 0},
            "authorityClaimed": True, "command": "/private/secret",
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                receipt = {**original, key: value}
                receipt["receiptDigest"] = canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"})
                self.assertEqual(validate_command_resource_receipt(receipt)["status"], "FAIL")
        cyclic = deepcopy(original)
        cyclic["children"] = [cyclic]
        self.assertEqual(validate_command_resource_receipt(cyclic)["status"], "FAIL")

    def test_bad_source_and_request_refuse_before_effect(self) -> None:
        effects = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = request(root)
            (root / "subject.py").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(LifecycleError):
                collect_command(value, ["version"], lambda: effects.append(True) or 0)
            value["prompt"] = "never-export-this"
            with self.assertRaises(LifecycleError):
                collect_command(value, ["version"], lambda: effects.append(True) or 0)
        self.assertEqual(effects, [])

    def test_output_refusal_and_post_effect_failure_are_distinct(self) -> None:
        effects = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root / "request.json", root / "receipt.json"
            write_json_create(source, request(root))
            write_json_create(output, {"occupied": True})
            with self.assertRaises(LifecycleError) as stopped:
                run_measured_command(source, output, ["version"], lambda: effects.append(1) or 0)
            self.assertEqual(stopped.exception.code, "command-measurement-output-exists")
            self.assertEqual(effects, [])
            with patch("agent_lifecycle.metrics.command_resources.write_json_create", side_effect=OSError("private-secret")):
                with self.assertRaises(LifecycleError) as failed:
                    run_measured_command(source, root / "new.json", ["version"], lambda: effects.append(1) or 0)
            self.assertEqual(failed.exception.code, "command-measurement-publication-failed")
            self.assertTrue(failed.exception.details["commandExecuted"])
            self.assertEqual(effects, [1])
            self.assertNotIn("private-secret", str(failed.exception.to_json()))

    def test_native_receipt_imports_into_existing_report_with_unknown_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, receipt = collect_command(request(root), ["version"], lambda: 0)
            write_json_create(root / "receipt.json", receipt)
            report = build_release_accounting("2.21.0", [Path("receipt.json")], project_root=root)
            self.assertEqual(validate_release_accounting(report)["status"], "PASS")
            self.assertEqual(report["totals"]["metrics"]["tokens"], {"status": "UNAVAILABLE", "value": None})
            self.assertEqual(report["entryCount"], 1)


if __name__ == "__main__":
    unittest.main()
