"""Proof-integrity receipts for findings, root causes and final evidence."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path

FINDING_SCHEMA = "agent-proof-finding.v1"
ROOT_CAUSE_SCHEMA = "agent-root-cause-evidence.v1"
FIX_IMPACT_SCHEMA = "agent-fix-impact-receipt.v1"
HASH_CHAIN_SCHEMA = "agent-receipt-hash-chain.v1"
HASH_CHAIN_MIGRATION_POLICY_SCHEMA = "agent-hash-chain-migration-policy.v1"
HASH_CHAIN_MIGRATION_VALIDATION_SCHEMA = "agent-hash-chain-migration-validation.v1"
PROOF_INTEGRITY_RECEIPT_SCHEMA = "agent-proof-integrity-receipt.v1"
PROOF_INTEGRITY_VALIDATION_SCHEMA = "agent-proof-integrity-validation.v1"

ROOT_CAUSE_STATUSES = {"CONFIRMED", "REJECTED", "INCONCLUSIVE"}
FIX_IMPACT_STATUSES = {"PASS", "FAIL", "BLOCKED"}
VALIDATION_STATUSES = {"PASS", "FAIL"}
DEFAULT_LEGACY_EXEMPTIONS = ("pre-chain-release", "external-archive", "artifact-unavailable")


def stable_finding_id(finding: dict[str, Any], *, namespace: str = "default") -> str:
    """Return a deterministic finding id from normalized finding identity fields."""

    identity_fields = finding_identity_fields(finding, namespace=namespace)
    return f"finding-{canonical_digest(identity_fields)}"


def finding_identity_fields(finding: dict[str, Any], *, namespace: str = "default") -> dict[str, Any]:
    """Project a finding to fields that should survive retries and line shifts."""

    if not isinstance(finding, dict):
        raise LifecycleError("invalid-proof-finding", "finding must be an object")
    location = finding.get("location") if isinstance(finding.get("location"), dict) else {}
    raw_path = (
        finding.get("path")
        or finding.get("file")
        or finding.get("sourcePath")
        or location.get("path")
        or location.get("file")
    )
    path = _optional_repo_path(raw_path, label="finding path")
    symbol = _optional_text(
        finding.get("symbol")
        or finding.get("function")
        or finding.get("scope")
        or location.get("symbol")
        or location.get("function")
    )
    rule_id = _optional_text(finding.get("ruleId") or finding.get("rule") or finding.get("code"))
    category = _optional_text(finding.get("category") or finding.get("type") or finding.get("kind"))
    severity = _optional_text(finding.get("severity"))
    message = _optional_text(finding.get("message") or finding.get("summary") or finding.get("title"))
    fields = {
        "namespace": _normalize_text(namespace),
        "ruleId": rule_id,
        "category": category,
        "severity": severity,
        "path": path,
        "symbol": symbol,
        "message": message,
    }
    useful = {key: value for key, value in fields.items() if key != "namespace" and value is not None}
    if not useful:
        raise LifecycleError("invalid-proof-finding", "finding has no stable identity fields")
    return fields


def build_finding_identity(finding: dict[str, Any], *, namespace: str = "default") -> dict[str, Any]:
    """Build a schema-backed stable finding identity."""

    identity_fields = finding_identity_fields(finding, namespace=namespace)
    finding_digest = canonical_digest(identity_fields)
    body = {
        "schemaVersion": FINDING_SCHEMA,
        "findingId": f"finding-{finding_digest}",
        "findingDigest": finding_digest,
        "identityFields": identity_fields,
        "sourceFindingDigest": canonical_digest(finding),
        "severity": _optional_text(finding.get("severity")),
        "status": _optional_text(finding.get("status")),
    }
    return body


def validate_finding_identity(identity: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(identity, dict):
        raise LifecycleError("invalid-proof-finding", "finding identity must be an object")
    if identity.get("schemaVersion") != FINDING_SCHEMA:
        blockers.append({"code": "proof-finding-schema-invalid"})
    identity_fields = identity.get("identityFields")
    if not isinstance(identity_fields, dict):
        blockers.append({"code": "proof-finding-fields-invalid"})
        identity_fields = {}
    expected_digest = canonical_digest(identity_fields)
    if identity.get("findingDigest") != expected_digest:
        blockers.append({"code": "proof-finding-digest-mismatch"})
    expected_id = f"finding-{expected_digest}"
    if identity.get("findingId") != expected_id:
        blockers.append({"code": "proof-finding-id-mismatch"})
    _check_digest(identity.get("sourceFindingDigest"), "proof-finding-source-digest", blockers)
    return _validation("agent-proof-finding-validation.v1", blockers, findingId=identity.get("findingId"))


def build_root_cause_evidence(
    *,
    finding_id: str,
    root_cause: dict[str, Any],
    evidence_ids: list[str],
    verifier: dict[str, Any],
    status: str = "CONFIRMED",
) -> dict[str, Any]:
    if not isinstance(root_cause, dict):
        raise LifecycleError("invalid-root-cause-evidence", "rootCause must be an object")
    _required_string(finding_id, label="findingId", code="invalid-root-cause-evidence")
    _string_list(evidence_ids, label="evidenceIds", code="invalid-root-cause-evidence", allow_empty=False)
    _verifier(verifier, code="invalid-root-cause-evidence")
    body = {
        "schemaVersion": ROOT_CAUSE_SCHEMA,
        "status": status,
        "findingId": finding_id,
        "rootCause": root_cause,
        "rootCauseDigest": canonical_digest(root_cause),
        "evidenceIds": list(evidence_ids),
        "verifier": dict(verifier),
        "productionPromotionClaimed": False,
    }
    return {**body, "evidenceDigest": canonical_digest(body)}


def validate_root_cause_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(evidence, dict):
        raise LifecycleError("invalid-root-cause-evidence", "root cause evidence must be an object")
    if evidence.get("schemaVersion") != ROOT_CAUSE_SCHEMA:
        blockers.append({"code": "root-cause-schema-invalid"})
    if evidence.get("status") not in ROOT_CAUSE_STATUSES:
        blockers.append({"code": "root-cause-status-invalid", "status": evidence.get("status")})
    if not isinstance(evidence.get("findingId"), str) or not evidence["findingId"]:
        blockers.append({"code": "root-cause-finding-id-missing"})
    root_cause = evidence.get("rootCause")
    if not isinstance(root_cause, dict):
        blockers.append({"code": "root-cause-payload-invalid"})
        root_cause = {}
    if evidence.get("rootCauseDigest") != canonical_digest(root_cause):
        blockers.append({"code": "root-cause-digest-mismatch"})
    _check_string_list(evidence.get("evidenceIds"), "root-cause-evidence-ids", blockers, allow_empty=False)
    _check_verifier(evidence.get("verifier"), "root-cause-verifier", blockers)
    if evidence.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "root-cause-production-claim"})
    expected = canonical_digest(_without_digest(evidence, "evidenceDigest"))
    if evidence.get("evidenceDigest") != expected:
        blockers.append({"code": "root-cause-evidence-digest-mismatch"})
    return _validation(
        "agent-root-cause-evidence-validation.v1",
        blockers,
        rootCauseDigest=evidence.get("rootCauseDigest"),
    )


def build_fix_impact_receipt(
    *,
    lineage: dict[str, Any],
    changed_files: list[str],
    related_finding_ids: list[str],
    root_cause_digests: list[str],
    behavior_changes: list[dict[str, Any]],
    preserved_behaviors: list[dict[str, Any]],
    validation_evidence_ids: list[str],
    collateral_damage: dict[str, Any],
    verifier: dict[str, Any],
    status: str = "PASS",
) -> dict[str, Any]:
    normalized_files = [normalize_repo_path(path, label="changedFiles") for path in changed_files]
    _lineage(lineage)
    _string_list(related_finding_ids, label="relatedFindingIds", code="invalid-fix-impact-receipt", allow_empty=False)
    _digest_list(root_cause_digests, label="rootCauseDigests", code="invalid-fix-impact-receipt")
    _object_list(behavior_changes, label="behaviorChanges", code="invalid-fix-impact-receipt", allow_empty=False)
    _object_list(preserved_behaviors, label="preservedBehaviors", code="invalid-fix-impact-receipt", allow_empty=False)
    _string_list(validation_evidence_ids, label="validationEvidenceIds", code="invalid-fix-impact-receipt", allow_empty=False)
    if not isinstance(collateral_damage, dict):
        raise LifecycleError("invalid-fix-impact-receipt", "collateralDamage must be an object")
    _verifier(verifier, code="invalid-fix-impact-receipt")
    body = {
        "schemaVersion": FIX_IMPACT_SCHEMA,
        "status": status,
        "lineage": dict(lineage),
        "changedFiles": normalized_files,
        "relatedFindingIds": list(related_finding_ids),
        "rootCauseDigests": list(root_cause_digests),
        "behaviorChanges": list(behavior_changes),
        "preservedBehaviors": list(preserved_behaviors),
        "validationEvidenceIds": list(validation_evidence_ids),
        "collateralDamage": dict(collateral_damage),
        "verifier": dict(verifier),
        "productionPromotionClaimed": False,
    }
    return {**body, "impactDigest": canonical_digest(body)}


def validate_fix_impact_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-fix-impact-receipt", "fix impact receipt must be an object")
    if receipt.get("schemaVersion") != FIX_IMPACT_SCHEMA:
        blockers.append({"code": "fix-impact-schema-invalid"})
    if receipt.get("status") not in FIX_IMPACT_STATUSES:
        blockers.append({"code": "fix-impact-status-invalid", "status": receipt.get("status")})
    _check_lineage(receipt.get("lineage"), blockers, code="fix-impact-lineage")
    _check_changed_files(receipt.get("changedFiles"), blockers)
    _check_string_list(receipt.get("relatedFindingIds"), "fix-impact-finding-ids", blockers, allow_empty=False)
    _check_digest_list(receipt.get("rootCauseDigests"), "fix-impact-root-cause-digests", blockers)
    _check_object_list(receipt.get("behaviorChanges"), "fix-impact-behavior-changes", blockers, allow_empty=False)
    _check_object_list(receipt.get("preservedBehaviors"), "fix-impact-preserved-behaviors", blockers, allow_empty=False)
    _check_string_list(receipt.get("validationEvidenceIds"), "fix-impact-validation-evidence", blockers, allow_empty=False)
    collateral = receipt.get("collateralDamage")
    if not isinstance(collateral, dict):
        blockers.append({"code": "fix-impact-collateral-damage-invalid"})
    elif collateral.get("status") not in {"PASS", "WAIVED"}:
        blockers.append({"code": "fix-impact-collateral-damage-status", "status": collateral.get("status")})
    _check_verifier(receipt.get("verifier"), "fix-impact-verifier", blockers)
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "fix-impact-production-claim"})
    expected = canonical_digest(_without_digest(receipt, "impactDigest"))
    if receipt.get("impactDigest") != expected:
        blockers.append({"code": "fix-impact-digest-mismatch"})
    return _validation("agent-fix-impact-receipt-validation.v1", blockers, impactDigest=receipt.get("impactDigest"))


def build_receipt_hash_chain(
    entries: list[dict[str, Any]],
    *,
    chain_id: str,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _required_string(chain_id, label="chainId", code="invalid-receipt-hash-chain")
    chain_entries: list[dict[str, Any]] = []
    previous: str | None = None
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise LifecycleError("invalid-receipt-hash-chain", "chain entries must be objects")
        artifact = _chain_artifact(item)
        entry_body = {
            "sequence": index,
            "artifact": artifact,
            "previousEntryHash": previous,
            "operationId": _optional_text(item.get("operationId")),
            "evidenceIds": _optional_string_list(item.get("evidenceIds")),
        }
        entry = {**entry_body, "entryHash": canonical_digest(entry_body)}
        chain_entries.append(entry)
        previous = entry["entryHash"]
    body = {
        "schemaVersion": HASH_CHAIN_SCHEMA,
        "status": "PASS",
        "chainId": chain_id,
        "appendOnly": True,
        "lineage": dict(lineage or {}),
        "entries": chain_entries,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    if not chain_entries:
        body["status"] = "FAIL"
        body["blockers"].append({"code": "receipt-hash-chain-empty"})
    return {**body, "chainDigest": canonical_digest(body)}


def validate_receipt_hash_chain(chain: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(chain, dict):
        raise LifecycleError("invalid-receipt-hash-chain", "receipt hash chain must be an object")
    if chain.get("schemaVersion") != HASH_CHAIN_SCHEMA:
        blockers.append({"code": "receipt-hash-chain-schema-invalid"})
    if chain.get("status") != "PASS":
        blockers.append({"code": "receipt-hash-chain-status-not-pass", "status": chain.get("status")})
    if not isinstance(chain.get("chainId"), str) or not chain["chainId"]:
        blockers.append({"code": "receipt-hash-chain-id-missing"})
    if chain.get("appendOnly") is not True:
        blockers.append({"code": "receipt-hash-chain-not-append-only"})
    entries = chain.get("entries")
    if not isinstance(entries, list) or not entries:
        blockers.append({"code": "receipt-hash-chain-entries-missing"})
        entries = []
    previous: str | None = None
    for expected_sequence, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            blockers.append({"code": "receipt-hash-chain-entry-invalid", "sequence": expected_sequence})
            continue
        _validate_chain_entry(entry, expected_sequence, previous, blockers)
        previous = entry.get("entryHash") if _is_digest(entry.get("entryHash")) else previous
    if chain.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "receipt-hash-chain-production-claim"})
    if chain.get("blockers"):
        blockers.append({"code": "receipt-hash-chain-has-blockers", "blockers": chain.get("blockers")})
    expected = canonical_digest(_without_digest(chain, "chainDigest"))
    if chain.get("chainDigest") != expected:
        blockers.append({"code": "receipt-hash-chain-digest-mismatch"})
    return _validation(
        "agent-receipt-hash-chain-validation.v1",
        blockers,
        chainDigest=chain.get("chainDigest"),
        chainStatus=chain.get("status"),
        entryCount=len(entries),
    )


def build_hash_chain_migration_policy(
    *,
    allowed_legacy_exemptions: list[str] | None = None,
    backfill_behavior: str = "backfill-hash-chain-when-artifacts-are-available",
) -> dict[str, Any]:
    exemptions = list(allowed_legacy_exemptions or DEFAULT_LEGACY_EXEMPTIONS)
    body = {
        "schemaVersion": HASH_CHAIN_MIGRATION_POLICY_SCHEMA,
        "status": "PASS",
        "mode": "required-for-new-runs",
        "newRunsRequireChain": True,
        "legacyReceiptPolicy": "explicit-exemption-or-backfill",
        "allowedLegacyExemptions": exemptions,
        "backfillBehavior": backfill_behavior,
        "productionPromotionClaimed": False,
    }
    return {**body, "policyDigest": canonical_digest(body)}


def validate_hash_chain_migration_policy(
    policy: dict[str, Any],
    *,
    new_run: bool,
    hash_chain: dict[str, Any] | None,
    legacy_exemption: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(policy, dict):
        raise LifecycleError("invalid-hash-chain-migration-policy", "hash chain migration policy must be an object")
    if policy.get("schemaVersion") != HASH_CHAIN_MIGRATION_POLICY_SCHEMA:
        blockers.append({"code": "hash-chain-policy-schema-invalid"})
    if policy.get("status") != "PASS":
        blockers.append({"code": "hash-chain-policy-status-not-pass", "status": policy.get("status")})
    if policy.get("mode") != "required-for-new-runs":
        blockers.append({"code": "hash-chain-policy-mode-invalid"})
    if policy.get("newRunsRequireChain") is not True:
        blockers.append({"code": "hash-chain-policy-new-runs-not-required"})
    if policy.get("legacyReceiptPolicy") != "explicit-exemption-or-backfill":
        blockers.append({"code": "hash-chain-policy-legacy-invalid"})
    exemptions = policy.get("allowedLegacyExemptions")
    if not isinstance(exemptions, list) or not exemptions or not all(isinstance(item, str) and item for item in exemptions):
        blockers.append({"code": "hash-chain-policy-exemptions-invalid"})
        exemptions = []
    if not isinstance(policy.get("backfillBehavior"), str) or not policy["backfillBehavior"]:
        blockers.append({"code": "hash-chain-policy-backfill-missing"})
    if policy.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "hash-chain-policy-production-claim"})
    expected = canonical_digest(_without_digest(policy, "policyDigest"))
    if policy.get("policyDigest") != expected:
        blockers.append({"code": "hash-chain-policy-digest-mismatch"})
    if new_run and hash_chain is None:
        blockers.append({"code": "hash-chain-required-for-new-run"})
    if not new_run and hash_chain is None:
        _validate_legacy_exemption(legacy_exemption, exemptions, blockers)
    body = {
        "schemaVersion": HASH_CHAIN_MIGRATION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "newRun": new_run,
        "blockers": blockers,
        "policyDigest": policy.get("policyDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_proof_integrity_receipt(
    *,
    lineage: dict[str, Any],
    findings: list[dict[str, Any]],
    root_causes: list[dict[str, Any]],
    fix_impact_receipts: list[dict[str, Any]],
    hash_chain: dict[str, Any],
    migration_policy: dict[str, Any] | None = None,
    required_evidence_ids: list[str] | None = None,
    verifier: dict[str, Any],
) -> dict[str, Any]:
    _lineage(lineage)
    _verifier(verifier, code="invalid-proof-integrity-receipt")
    body = {
        "schemaVersion": PROOF_INTEGRITY_RECEIPT_SCHEMA,
        "status": "PASS",
        "lineage": dict(lineage),
        "requiredEvidenceIds": list(required_evidence_ids or []),
        "findings": list(findings),
        "rootCauses": list(root_causes),
        "fixImpactReceipts": list(fix_impact_receipts),
        "hashChain": dict(hash_chain),
        "migrationPolicy": dict(migration_policy or build_hash_chain_migration_policy()),
        "blockers": [],
        "verifier": dict(verifier),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_proof_integrity_receipt(
    receipt: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    final_audit: dict[str, Any] | None = None,
    final_proof: dict[str, Any] | None = None,
    require_hash_chain: bool = True,
    new_run: bool = True,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-proof-integrity-receipt", "proof integrity receipt must be an object")
    if receipt.get("schemaVersion") != PROOF_INTEGRITY_RECEIPT_SCHEMA:
        blockers.append({"code": "proof-integrity-schema-invalid"})
    if receipt.get("status") != "PASS":
        blockers.append({"code": "proof-integrity-status-not-pass", "status": receipt.get("status")})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "proof-integrity-production-claim"})
    _check_lineage(receipt.get("lineage"), blockers, code="proof-integrity-lineage")
    _compare_lineage(receipt.get("lineage"), state, final_audit, final_proof, blockers)
    findings = _object_items(receipt.get("findings"), "proof-integrity-findings", blockers)
    root_causes = _object_items(receipt.get("rootCauses"), "proof-integrity-root-causes", blockers)
    fix_impacts = _object_items(receipt.get("fixImpactReceipts"), "proof-integrity-fix-impacts", blockers)
    finding_ids = _validate_findings(findings, blockers)
    root_cause_digests = _validate_root_causes(root_causes, finding_ids, blockers)
    _validate_fix_impacts(fix_impacts, finding_ids, root_cause_digests, blockers)
    _validate_required_sets(receipt, final_audit, finding_ids, root_cause_digests, fix_impacts, blockers)
    hash_chain = receipt.get("hashChain")
    chain_status: str | None = None
    if require_hash_chain and not isinstance(hash_chain, dict):
        blockers.append({"code": "proof-integrity-hash-chain-missing"})
        hash_chain = None
    if isinstance(hash_chain, dict):
        chain_validation = validate_receipt_hash_chain(hash_chain)
        chain_status = chain_validation["status"]
        if chain_validation["status"] != "PASS":
            blockers.append({"code": "proof-integrity-hash-chain-invalid", "validation": chain_validation})
    policy = receipt.get("migrationPolicy")
    if not isinstance(policy, dict):
        blockers.append({"code": "proof-integrity-migration-policy-missing"})
    else:
        migration_validation = validate_hash_chain_migration_policy(
            policy,
            new_run=new_run,
            hash_chain=hash_chain if isinstance(hash_chain, dict) and chain_status == "PASS" else None,
            legacy_exemption=receipt.get("legacyHashChainExemption"),
        )
        if migration_validation["status"] != "PASS":
            blockers.append({"code": "proof-integrity-migration-policy-invalid", "validation": migration_validation})
    if receipt.get("blockers"):
        blockers.append({"code": "proof-integrity-receipt-has-blockers", "blockers": receipt.get("blockers")})
    _check_verifier(receipt.get("verifier"), "proof-integrity-verifier", blockers)
    expected = canonical_digest(_without_digest(receipt, "receiptDigest"))
    if receipt.get("receiptDigest") != expected:
        blockers.append({"code": "proof-integrity-receipt-digest-mismatch"})
    body = {
        "schemaVersion": PROOF_INTEGRITY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "findingCount": len(findings),
        "rootCauseCount": len(root_causes),
        "fixImpactCount": len(fix_impacts),
        "chainStatus": chain_status,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_proof_integrity_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("proof-integrity-validation-failed", "proof integrity validation failed", {"validation": validation})
    return validation


def _validate_findings(findings: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> set[str]:
    finding_ids: set[str] = set()
    for index, finding in enumerate(findings):
        validation = validate_finding_identity(finding)
        if validation["status"] != "PASS":
            blockers.append({"code": "proof-integrity-finding-invalid", "index": index, "validation": validation})
        finding_id = finding.get("findingId")
        if isinstance(finding_id, str) and finding_id:
            if finding_id in finding_ids:
                blockers.append({"code": "proof-integrity-finding-duplicate", "findingId": finding_id})
            finding_ids.add(finding_id)
    return finding_ids


def _validate_root_causes(
    root_causes: list[dict[str, Any]],
    finding_ids: set[str],
    blockers: list[dict[str, Any]],
) -> set[str]:
    root_cause_digests: set[str] = set()
    root_causes_by_finding: set[str] = set()
    for index, evidence in enumerate(root_causes):
        validation = validate_root_cause_evidence(evidence)
        if validation["status"] != "PASS":
            blockers.append({"code": "proof-integrity-root-cause-invalid", "index": index, "validation": validation})
        if evidence.get("status") != "CONFIRMED":
            blockers.append({"code": "proof-integrity-root-cause-not-confirmed", "index": index, "status": evidence.get("status")})
        finding_id = evidence.get("findingId")
        if isinstance(finding_id, str) and finding_id:
            root_causes_by_finding.add(finding_id)
            if finding_ids and finding_id not in finding_ids:
                blockers.append({"code": "proof-integrity-root-cause-unmatched-finding", "findingId": finding_id})
        digest = evidence.get("rootCauseDigest")
        if _is_digest(digest):
            root_cause_digests.add(str(digest))
    for finding_id in sorted(finding_ids.difference(root_causes_by_finding)):
        blockers.append({"code": "proof-integrity-root-cause-missing", "findingId": finding_id})
    return root_cause_digests


def _validate_fix_impacts(
    fix_impacts: list[dict[str, Any]],
    finding_ids: set[str],
    root_cause_digests: set[str],
    blockers: list[dict[str, Any]],
) -> None:
    covered_findings: set[str] = set()
    covered_root_causes: set[str] = set()
    for index, receipt in enumerate(fix_impacts):
        validation = validate_fix_impact_receipt(receipt)
        if validation["status"] != "PASS":
            blockers.append({"code": "proof-integrity-fix-impact-invalid", "index": index, "validation": validation})
        if receipt.get("status") != "PASS":
            blockers.append({"code": "proof-integrity-fix-impact-not-pass", "index": index, "status": receipt.get("status")})
        for finding_id in receipt.get("relatedFindingIds") or []:
            if isinstance(finding_id, str):
                covered_findings.add(finding_id)
                if finding_ids and finding_id not in finding_ids:
                    blockers.append({"code": "proof-integrity-fix-impact-unmatched-finding", "findingId": finding_id})
        for digest in receipt.get("rootCauseDigests") or []:
            if isinstance(digest, str):
                covered_root_causes.add(digest)
                if root_cause_digests and digest not in root_cause_digests:
                    blockers.append({"code": "proof-integrity-fix-impact-unmatched-root-cause", "rootCauseDigest": digest})
    for finding_id in sorted(finding_ids.difference(covered_findings)):
        blockers.append({"code": "proof-integrity-fix-impact-missing", "findingId": finding_id})
    for digest in sorted(root_cause_digests.difference(covered_root_causes)):
        blockers.append({"code": "proof-integrity-root-cause-fix-impact-missing", "rootCauseDigest": digest})


def _validate_required_sets(
    receipt: dict[str, Any],
    final_audit: dict[str, Any] | None,
    finding_ids: set[str],
    root_cause_digests: set[str],
    fix_impacts: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    requirements = final_audit.get("proofIntegrityEvidence") if isinstance(final_audit, dict) else None
    if not isinstance(requirements, dict):
        return
    required_findings = set(_optional_string_list(requirements.get("requiredFindingIds")))
    required_root_causes = set(_optional_string_list(requirements.get("requiredRootCauseDigests")))
    required_fix_impacts = set(_optional_string_list(requirements.get("requiredFixImpactDigests")))
    fix_impact_digests = {str(item.get("impactDigest")) for item in fix_impacts if _is_digest(item.get("impactDigest"))}
    for finding_id in sorted(required_findings.difference(finding_ids)):
        blockers.append({"code": "proof-integrity-required-finding-missing", "findingId": finding_id})
    for digest in sorted(required_root_causes.difference(root_cause_digests)):
        blockers.append({"code": "proof-integrity-required-root-cause-missing", "rootCauseDigest": digest})
    for digest in sorted(required_fix_impacts.difference(fix_impact_digests)):
        blockers.append({"code": "proof-integrity-required-fix-impact-missing", "impactDigest": digest})
    required_evidence_ids = set(_optional_string_list(requirements.get("requiredEvidenceIds")))
    receipt_evidence_ids = set(_optional_string_list(receipt.get("requiredEvidenceIds")))
    for evidence_id in sorted(required_evidence_ids.difference(receipt_evidence_ids)):
        blockers.append({"code": "proof-integrity-required-evidence-id-missing", "evidenceId": evidence_id})


def _validate_chain_entry(
    entry: dict[str, Any],
    expected_sequence: int,
    expected_previous: str | None,
    blockers: list[dict[str, Any]],
) -> None:
    if entry.get("sequence") != expected_sequence:
        blockers.append({"code": "receipt-hash-chain-sequence-mismatch", "sequence": expected_sequence})
    artifact = entry.get("artifact")
    if not isinstance(artifact, dict):
        blockers.append({"code": "receipt-hash-chain-artifact-invalid", "sequence": expected_sequence})
    else:
        try:
            normalize_repo_path(str(artifact.get("path")), label="chain artifact path")
        except LifecycleError as exc:
            blockers.append({"code": "receipt-hash-chain-artifact-path-invalid", "sequence": expected_sequence, "reason": exc.code})
        _check_digest(artifact.get("digest"), "receipt-hash-chain-artifact-digest-invalid", blockers)
    if entry.get("previousEntryHash") != expected_previous:
        blockers.append({"code": "receipt-hash-chain-previous-mismatch", "sequence": expected_sequence})
    expected_hash = canonical_digest(_without_digest(entry, "entryHash"))
    if entry.get("entryHash") != expected_hash:
        blockers.append({"code": "receipt-hash-chain-entry-hash-mismatch", "sequence": expected_sequence})


def _chain_artifact(item: dict[str, Any]) -> dict[str, Any]:
    raw_artifact = item.get("artifact") if isinstance(item.get("artifact"), dict) else item
    path = normalize_repo_path(str(raw_artifact.get("path") or raw_artifact.get("sourcePath")), label="chain artifact path")
    digest = raw_artifact.get("digest") or raw_artifact.get("artifactDigest") or raw_artifact.get("sha256")
    if not _is_digest(digest):
        raise LifecycleError("invalid-receipt-hash-chain", "chain artifact digest must be a 64-character hex digest")
    artifact = {"path": path, "digest": str(digest)}
    schema_version = raw_artifact.get("schemaVersion") or item.get("artifactType")
    if isinstance(schema_version, str) and schema_version:
        artifact["schemaVersion"] = schema_version
    return artifact


def _compare_lineage(
    lineage: Any,
    state: dict[str, Any] | None,
    final_audit: dict[str, Any] | None,
    final_proof: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> None:
    if not isinstance(lineage, dict):
        return
    for label, artifact in (("state", state), ("final-audit", final_audit), ("final-proof", final_proof)):
        if not isinstance(artifact, dict):
            continue
        for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision"):
            if key in artifact and lineage.get(key) != artifact.get(key):
                blockers.append({"code": "proof-integrity-lineage-mismatch", "artifact": label, "field": key})


def _validate_legacy_exemption(
    exemption: dict[str, Any] | None,
    allowed_reasons: list[Any],
    blockers: list[dict[str, Any]],
) -> None:
    if not isinstance(exemption, dict):
        blockers.append({"code": "hash-chain-legacy-exemption-required"})
        return
    reason = exemption.get("reason")
    if reason not in allowed_reasons:
        blockers.append({"code": "hash-chain-legacy-exemption-reason-invalid", "reason": reason})
    if not isinstance(exemption.get("approvedBy"), str) or not exemption["approvedBy"]:
        blockers.append({"code": "hash-chain-legacy-exemption-approval-missing"})


def _validation(schema: str, blockers: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    body = {
        "schemaVersion": schema,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        **extra,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _lineage(lineage: dict[str, Any]) -> None:
    if not isinstance(lineage, dict):
        raise LifecycleError("invalid-lineage", "lineage must be an object")
    missing = [key for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision") if key not in lineage]
    if missing:
        raise LifecycleError("invalid-lineage", "lineage is missing required fields", {"fields": missing})
    if not _is_digest(lineage.get("planDigest")):
        raise LifecycleError("invalid-lineage", "lineage.planDigest must be a 64-character digest")


def _check_lineage(lineage: Any, blockers: list[dict[str, Any]], *, code: str) -> None:
    if not isinstance(lineage, dict):
        blockers.append({"code": f"{code}-invalid"})
        return
    for key in ("runId", "packageId", "sourceRevision"):
        if not isinstance(lineage.get(key), str) or not lineage[key]:
            blockers.append({"code": f"{code}-{key}-missing"})
    if not isinstance(lineage.get("planRevision"), int) or lineage["planRevision"] < 1:
        blockers.append({"code": f"{code}-plan-revision-invalid"})
    _check_digest(lineage.get("planDigest"), f"{code}-plan-digest-invalid", blockers)


def _object_items(value: Any, code: str, blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        blockers.append({"code": f"{code}-invalid"})
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            blockers.append({"code": f"{code}-item-invalid", "index": index})
        else:
            items.append(item)
    return items


def _object_list(value: list[dict[str, Any]], *, label: str, code: str, allow_empty: bool) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise LifecycleError(code, f"{label} must be a non-empty array")
    if not all(isinstance(item, dict) for item in value):
        raise LifecycleError(code, f"{label} entries must be objects")


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        blockers.append({"code": code})
        return
    if not all(isinstance(item, dict) for item in value):
        blockers.append({"code": f"{code}-item-invalid"})


def _string_list(value: list[str], *, label: str, code: str, allow_empty: bool) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise LifecycleError(code, f"{label} must be a non-empty array")
    if not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(code, f"{label} entries must be non-empty strings")


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        blockers.append({"code": code})
        return
    if not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": f"{code}-item-invalid"})


def _optional_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _digest_list(value: list[str], *, label: str, code: str) -> None:
    if not isinstance(value, list) or not value:
        raise LifecycleError(code, f"{label} must be a non-empty array")
    if not all(_is_digest(item) for item in value):
        raise LifecycleError(code, f"{label} entries must be 64-character digests")


def _check_digest_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value:
        blockers.append({"code": code})
        return
    if not all(_is_digest(item) for item in value):
        blockers.append({"code": f"{code}-item-invalid"})


def _check_changed_files(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value:
        blockers.append({"code": "fix-impact-changed-files-missing"})
        return
    for index, path in enumerate(value):
        try:
            normalize_repo_path(str(path), label="changedFiles")
        except LifecycleError as exc:
            blockers.append({"code": "fix-impact-changed-file-invalid", "index": index, "reason": exc.code})


def _verifier(verifier: dict[str, Any], *, code: str) -> None:
    if not isinstance(verifier, dict) or not isinstance(verifier.get("id"), str) or not verifier["id"]:
        raise LifecycleError(code, "verifier.id is required")


def _check_verifier(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
        blockers.append({"code": code})


def _required_string(value: str, *, label: str, code: str) -> None:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} is required")


def _optional_repo_path(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    return normalize_repo_path(str(value), label=label)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _normalize_text(str(value))
    return text or None


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _is_digest(value):
        blockers.append({"code": code})


def _without_digest(value: dict[str, Any], digest_key: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != digest_key}


__all__ = [
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
