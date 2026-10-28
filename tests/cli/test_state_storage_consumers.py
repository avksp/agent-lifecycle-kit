"""Portable refusal tests for the actual isolated incident rehearsal CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools.qualification.workflow_storage import INCIDENT_HEAD, authority_containment

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/qualification/workflow_storage.py"


class RehearsalCLIContractTests(unittest.TestCase):
    def test_migration_comparison_resolves_every_immutable_history_body(self):
        from tools.qualification.workflow_storage import verify_migration

        from agent_lifecycle.contracts import canonical_bytes
        from agent_lifecycle.workflow import migrate_workflow_state
        from agent_lifecycle.workflow.state import load_state
        from tests.workflow.test_state_storage import state_fixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "state.json"
            before = state_fixture()
            before.update(
                stateRevision=64,
                phase="BLOCKED",
                eventLog="events.jsonl",
                blocker={"code": "fixture", "reason": "retain", "scope": "plan", "recoveryRoute": "adopt-plan"},
            )
            raw = canonical_bytes(before) + b"\n"
            path.write_bytes(raw)
            migrate_workflow_state(
                path,
                operation_id="comparison-fixture",
                expected_revision=64,
                source_revision="source",
                target_schema="agent-workflow-state.v5",
            )
            after = load_state(path)
            events = root / "events.jsonl"
            report = {"incidentBefore": {"state": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}}}
            saved = path.read_bytes(), events.read_bytes()
            verify_migration(root, before, after, events, b"", report)
            for variant in ("history-metadata", "historical-evidence", "current-evidence", "extra-current-field"):
                old, new = deepcopy(before), deepcopy(after)
                if variant == "history-metadata":
                    old["priorSnapshots"][0]["financialRole"] = "CHANGED"
                elif variant == "historical-evidence":
                    old["priorSnapshots"][0]["tasks"][0]["ownershipReceipt"]["entries"][0]["path"] = "changed"
                elif variant == "current-evidence":
                    old["tasks"][0]["ownershipReceipt"]["entries"][0]["path"] = "changed"
                else:
                    new["tasks"][0]["unexpected"] = True
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    verify_migration(root, old, new, events, b"", report)
            self.assertEqual((path.read_bytes(), events.read_bytes()), saved)

    def test_negative_cli_inputs_never_materialize_or_touch_protected_inputs(self):
        variants = (
            "unknown-field",
            "missing-map",
            "source-overlap",
            "backup-overlap",
            "ancestor",
            "duplicate",
            "case-alias",
            "traversal",
            "backslash",
            "git-metadata",
            "reserved-name",
            "unordered",
            "raw-hash",
            "negative-bytes",
            "missing-identity",
            "source-head",
            "timeout",
        )
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                source, backup = root / "source", root / "backup"
                source.mkdir()
                backup.mkdir()
                (source / "marker").write_bytes(b"protected live marker")
                rows = []
                for name in ("a", "z"):
                    (backup / name).write_bytes(name.encode())
                    rows.append(
                        {
                            "originalPath": name,
                            "archivedPath": name,
                            "bytes": 1,
                            "sha256": hashlib.sha256(name.encode()).hexdigest(),
                        }
                    )
                entry = {"path": "a", "bytes": 1, "sha256": rows[0]["sha256"]}
                value = {
                    "schemaVersion": "rmk-replay-input.v1",
                    "sourceRoot": str(source),
                    "backupRoot": str(backup),
                    "sourceHead": INCIDENT_HEAD,
                    "runtimeSourceRevision": "a" * 40,
                    "state": entry,
                    "eventLog": entry,
                    "relocations": entry,
                    "files": rows,
                }
                replica = root / "replica"
                timeout = "10"
                if variant == "unknown-field":
                    value["extra"] = True
                elif variant == "missing-map":
                    value["files"] = []
                elif variant in {"source-overlap", "backup-overlap", "ancestor"}:
                    replica = {"source-overlap": source / "replica", "backup-overlap": backup, "ancestor": root}[
                        variant
                    ]
                elif variant in {"duplicate", "case-alias"}:
                    rows[1]["originalPath"] = "a" if variant == "duplicate" else "A"
                elif variant in {"traversal", "backslash", "git-metadata", "reserved-name"}:
                    rows[0]["originalPath"] = {
                        "traversal": "../escape",
                        "backslash": "dir\\file",
                        "git-metadata": ".git/config",
                        "reserved-name": "CON",
                    }[variant]
                elif variant == "unordered":
                    rows.reverse()
                elif variant == "raw-hash":
                    rows[0]["sha256"] = "f" * 64
                elif variant == "negative-bytes":
                    rows[0]["bytes"] = -1
                elif variant == "missing-identity":
                    value["state"] = {**entry, "path": "missing"}
                elif variant == "source-head":
                    value["sourceHead"] = "f" * 40
                else:
                    timeout = "301"
                input_path, out = root / "input.json", root / "report.json"
                input_path.write_text(json.dumps(value), encoding="utf-8")
                before = protected_bytes(source, backup)
                argv = [
                    sys.executable,
                    "-B",
                    str(TOOL),
                    "--scenario",
                    "rmk-migration",
                    "--input",
                    str(input_path),
                    "--replica-root",
                    str(replica),
                    "--out",
                    str(out),
                    "--timeout-seconds",
                    timeout,
                ]
                child = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
                self.assertEqual(child.returncode, 2, child.stdout + child.stderr)
                self.assertEqual(protected_bytes(source, backup), before)
                self.assertFalse((root / "replica").exists())
                report = json.loads(out.read_bytes())
                self.assertEqual(report["status"], "FAIL")
                self.assertFalse(report.get("observations"), report)

    def test_output_inside_protected_root_is_refused_without_report_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "source"
            source.mkdir()
            input_path = root / "input.json"
            input_path.write_text(json.dumps({"sourceRoot": str(source)}), encoding="utf-8")
            child = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(TOOL),
                    "--scenario",
                    "rmk-migration",
                    "--input",
                    str(input_path),
                    "--replica-root",
                    str(root / "replica"),
                    "--out",
                    str(source / "report.json"),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(child.returncode, 2)
            self.assertEqual(list(source.iterdir()), [])

    def test_containment_checks_artifact_templates_and_manifest_paths(self):
        from tests.workflow.storage_helpers import build_native_fixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "replica"
            path, _, _, _, _ = build_native_fixture(ROOT, root)
            subprocess.run(
                ["git", "config", "core.hooksPath", str(root / ".git/disabled-hooks")],
                cwd=root,
                capture_output=True,
                check=True,
            )
            state = json.loads(path.read_bytes())
            state["tasks"][0]["artifactPaths"]["result"] = "../outside/result.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "aliased|escaping"):
                authority_containment(root, path)


def protected_bytes(*roots):
    return {str(path): path.read_bytes() for root in roots for path in root.rglob("*") if path.is_file()}


if __name__ == "__main__":
    unittest.main()
