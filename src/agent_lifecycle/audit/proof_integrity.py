"""Compatibility facade for proof-integrity contracts and audit receipts."""

from __future__ import annotations

from agent_lifecycle.contracts.proof_validation import (
    DEFAULT_LEGACY_EXEMPTIONS,
    FINDING_SCHEMA,
    FIX_IMPACT_SCHEMA,
    HASH_CHAIN_MIGRATION_POLICY_SCHEMA,
    HASH_CHAIN_MIGRATION_VALIDATION_SCHEMA,
    HASH_CHAIN_SCHEMA,
    PROOF_INTEGRITY_RECEIPT_SCHEMA,
    PROOF_INTEGRITY_VALIDATION_SCHEMA,
    ROOT_CAUSE_SCHEMA,
)
from agent_lifecycle.contracts.proof_validation import *  # noqa: F401,F403

__all__ = [
    "DEFAULT_LEGACY_EXEMPTIONS",
    "FINDING_SCHEMA",
    "FIX_IMPACT_SCHEMA",
    "HASH_CHAIN_MIGRATION_POLICY_SCHEMA",
    "HASH_CHAIN_MIGRATION_VALIDATION_SCHEMA",
    "HASH_CHAIN_SCHEMA",
    "PROOF_INTEGRITY_RECEIPT_SCHEMA",
    "PROOF_INTEGRITY_VALIDATION_SCHEMA",
    "ROOT_CAUSE_SCHEMA",
    "build_finding_identity",
    "build_fix_impact_receipt",
    "build_hash_chain_migration_policy",
    "build_proof_integrity_receipt",
    "build_receipt_hash_chain",
    "build_root_cause_evidence",
    "finding_identity_fields",
    "require_proof_integrity_pass",
    "stable_finding_id",
    "validate_finding_identity",
    "validate_fix_impact_receipt",
    "validate_hash_chain_migration_policy",
    "validate_proof_integrity_receipt",
    "validate_receipt_hash_chain",
    "validate_root_cause_evidence",
]
