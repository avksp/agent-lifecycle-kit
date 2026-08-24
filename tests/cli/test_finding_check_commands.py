from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.planning.deltas import build_plan_delta


class FindingCheckCliTests(unittest.TestCase):
    def test_cli_propose_validate_accept_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            finding = root / "finding.json"
            delta = root / "delta.json"
            check = root / "check.json"
            scope = root / "scope.json"
            proposal = root / "proposal.json"
            accepted = root / "accepted.json"
            evidence = root / "evidence.json"
            _write(finding, {"path": "src/fix.py", "ruleId": "H1", "severity": "HIGH", "message": "issue"})
            _write(delta, build_plan_delta(_manifest(1), _manifest(2)))
            _write(check, {"id": "check", "route": "release/86"})
            _write(scope, {"paths": ["src/fix.py"]})

            code, proposal_payload = _run(
                [
                    "plan", "finding-check", "propose", "--finding", str(finding), "--delta", str(delta),
                    "--check", str(check), "--scope", str(scope), "--owner", "WS86-01",
                    "--source-revision", "a" * 40, "--out", str(proposal),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(proposal_payload["status"], "PASS")

            code, validated = _run(["plan", "finding-check", "validate", "--proposal", str(proposal)])
            self.assertEqual(code, 0)
            self.assertEqual(validated["status"], "PASS")

            code, accepted_payload = _run(
                [
                    "plan", "finding-check", "accept", "--proposal", str(proposal),
                    "--authorization", str(_authorization(root)), "--out", str(accepted),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(accepted_payload["binding"]["status"], "ACCEPTED")
            accepted.write_text(json.dumps(accepted_payload["binding"]), encoding="utf-8")

            code, evidence_payload = _run(
                [
                    "plan", "finding-check", "evidence", "--binding", str(accepted), "--result", "PASS",
                    "--source-revision", "a" * 40, "--evidence-id", "EV86", "--out", str(evidence),
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(evidence_payload["readOnly"])


def _run(arguments: list[str]) -> tuple[int, dict]:
    output = StringIO()
    with contextlib.redirect_stdout(output):
        code = main(arguments)
    return code, json.loads(output.getvalue())


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _authorization(root: Path) -> Path:
    path = root / "authorization.json"
    _write(path, {"status": "APPROVED", "actor": "operator", "operationId": "accept-1", "authorityClaimed": False})
    return path


def _manifest(revision: int) -> dict:
    return {
        "package": {"id": "release-1-86"},
        "planRevision": revision,
        "status": "FROZEN",
        "baseRevision": {"ref": "main", "sha": "a" * 40},
        "specification": {"requirements": [{"id": "R1", "description": "issue"}]},
        "workstreams": [{"id": "WS1", "writes": ["src/fix.py"], "evidenceIds": ["EV1"]}],
        "acceptance": {"criteria": [{"id": "AC1", "requirementIds": ["R1"], "evidenceIds": ["EV1"]}]},
        "validation": {"extraEvidence": ["EV1"]},
        "securityGates": ["offline"],
        "finalAuditGates": ["[AC1|EV1] evidence"],
    }


if __name__ == "__main__":
    unittest.main()
