from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli

ROOT = Path(__file__).resolve().parents[2]


class StrategyCliTests(unittest.TestCase):
    def test_resolve_writes_bound_provider_neutral_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, lock, state = _write_inputs(root)
            out = root / "strategy.json"
            args = _args(manifest, lock, state, out)

            code, payload = _run_cli(args)

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["lineage"]["taskId"], "WS-01")
            self.assertEqual(payload["quality"]["resolvedRiskTier"], "S2")
            self.assertEqual(payload["packet"]["mode"], "FULL")
            self.assertFalse(payload["authority"]["canAuthorizeImplementation"])
            self.assertFalse(payload["authority"]["automaticAdoptionEligible"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)

            repeat_code, repeat = _run_cli(args)
            self.assertEqual(repeat_code, 2)
            self.assertEqual(repeat["code"], "output-already-exists")

    def test_resolve_rejects_stale_state_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, lock, state = _write_inputs(root)
            out = root / "strategy.json"
            args = _args(manifest, lock, state, out)
            revision_index = args.index("--expected-revision") + 1
            args[revision_index] = "2"

            code, payload = _run_cli(args)

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "strategy-state-revision-mismatch")
            self.assertFalse(out.exists())


def _args(manifest: Path, lock: Path, state: Path, out: Path) -> list[str]:
    return [
        "strategy",
        "resolve",
        "--manifest",
        str(manifest),
        "--lock",
        str(lock),
        "--state",
        str(state),
        "--task",
        "WS-01",
        "--operation-id",
        "strategy-cli",
        "--expected-revision",
        "3",
        "--source-revision",
        "source-sha",
        "--adapter",
        "codex",
        "--host-model-profile",
        str(ROOT / "profiles/hosts/codex-live-profile.v1.json"),
        "--out",
        str(out),
    ]


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    manifest_payload = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "strategy-cli", "title": "Security change"},
        "specification": {
            "tier": "S2",
            "tierResolutionRequest": {
                "riskFlags": {"security": True},
                "capabilityHints": ["architecture"],
            },
        },
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Apply security change",
                "owner": "worker",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
            }
        ],
        "acceptance": {"criteria": [{"id": "AC-1", "evidenceIds": ["EV-1"]}]},
    }
    digest = canonical_digest(manifest_payload)
    payloads = {
        "manifest.json": manifest_payload,
        "lock.json": {
            "schemaVersion": "agent-plan-lock.v1",
            "packageId": "strategy-cli",
            "planRevision": 1,
            "manifestHash": digest,
        },
        "state.json": {
            "runId": "run-cli",
            "packageId": "strategy-cli",
            "planRevision": 1,
            "planDigest": digest,
            "stateRevision": 3,
            "sourceRevision": "source-sha",
            "tasks": [{"id": "WS-01", "attemptCount": 0}],
        },
    }
    paths: list[Path] = []
    for name, payload in payloads.items():
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    return paths[0], paths[1], paths[2]


if __name__ == "__main__":
    unittest.main()
