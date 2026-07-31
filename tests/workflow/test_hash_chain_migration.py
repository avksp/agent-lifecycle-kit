from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.audit.proof_integrity import (  # noqa: E402
    build_hash_chain_migration_policy,
    build_receipt_hash_chain,
    validate_hash_chain_migration_policy,
)


class HashChainMigrationTests(unittest.TestCase):
    def test_new_runs_require_hash_chain(self) -> None:
        policy = build_hash_chain_migration_policy()

        validation = validate_hash_chain_migration_policy(policy, new_run=True, hash_chain=None)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("hash-chain-required-for-new-run", _codes(validation))

    def test_legacy_run_without_chain_requires_explicit_exemption(self) -> None:
        policy = build_hash_chain_migration_policy()

        validation = validate_hash_chain_migration_policy(
            policy,
            new_run=False,
            hash_chain=None,
            legacy_exemption={"reason": "pre-chain-release", "approvedBy": "release-lead"},
        )

        self.assertEqual(validation["status"], "PASS")

    def test_legacy_exemption_reason_must_be_allowed(self) -> None:
        policy = build_hash_chain_migration_policy(allowed_legacy_exemptions=["pre-chain-release"])

        validation = validate_hash_chain_migration_policy(
            policy,
            new_run=False,
            hash_chain=None,
            legacy_exemption={"reason": "unknown", "approvedBy": "release-lead"},
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("hash-chain-legacy-exemption-reason-invalid", _codes(validation))

    def test_new_run_with_valid_chain_passes_migration_policy(self) -> None:
        policy = build_hash_chain_migration_policy()
        chain = build_receipt_hash_chain(
            [{"path": "final/proof-integrity.json", "digest": "1" * 64}],
            chain_id="run-proof",
            lineage={
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
            },
        )

        validation = validate_hash_chain_migration_policy(policy, new_run=True, hash_chain=chain)

        self.assertEqual(validation["status"], "PASS")


def _codes(validation: dict) -> set[str]:
    return {
        blocker["code"]
        for blocker in validation.get("blockers", [])
        if isinstance(blocker, dict) and isinstance(blocker.get("code"), str)
    }


if __name__ == "__main__":
    unittest.main()
