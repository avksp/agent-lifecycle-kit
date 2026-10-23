"""Internal finalization shapes after the existing domain validators have run.

These TypedDicts describe Python inputs and canonical JSON records; they do not
validate untrusted data or grant lifecycle authority. Nested evidence retains
its validated JSON shape because its own contract owns validation. In particular,
nullable evidence and unknown usage values must not be replaced with defaults.
"""

from typing import Any, Literal, NotRequired, TypedDict


class FinalizationProofInputs(TypedDict):
    """Keyword bundle prepared for the workflow's final-proof builder.

    The lifecycle stop gate is evaluated against a preview and supplied separately
    to the builder. Source assurance is absent until its existing reader supplies
    it; every other optional artifact has an explicit null value when absent.
    """

    operation_id: str
    final_audit: dict[str, Any]
    completion_check_receipt: dict[str, Any] | None
    completion_gate: dict[str, Any] | None
    goal_record: dict[str, Any] | None
    follow_up_register: dict[str, Any] | None
    proof_integrity: dict[str, Any] | None
    final_implementation_audit: dict[str, Any] | None
    release_full_validation: dict[str, Any] | None
    finalization_gate_receipts: list[dict[str, Any]]
    review_mesh_quorum: dict[str, Any] | None
    reason: str
    source_usage_assurance: NotRequired[dict[str, Any] | None]


class AcceptedTaskProof(TypedDict):
    """Projection of an accepted task, with optional source usage evidence."""

    id: str
    attempt: int
    review: dict[str, Any] | None
    usageAssurance: NotRequired[dict[str, Any]]


class FinalizationProofBody(TypedDict):
    """The exact body hashed by the existing final-proof builder."""

    schemaVersion: Literal["agent-run-final-proof.v1"]
    runId: str
    packageId: str
    planRevision: int
    planDigest: str
    sourceRevision: str
    operationId: str
    stateRevisionBeforeFinalization: int
    semanticStatus: Literal["READY_FOR_FINALIZATION"]
    productionPromotionClaimed: Literal[False]
    acceptedTasks: list[AcceptedTaskProof]
    finalAudit: dict[str, Any]
    completionCheck: dict[str, Any] | None
    completionGate: dict[str, Any] | None
    goalRecord: dict[str, Any] | None
    followUpRegister: dict[str, Any] | None
    proofIntegrity: dict[str, Any] | None
    finalImplementationAudit: dict[str, Any] | None
    releaseFullValidation: dict[str, Any] | None
    finalizationGateReceipts: list[dict[str, Any]]
    reviewMeshQuorum: dict[str, Any] | None
    lifecycleControlStop: dict[str, Any] | None
    reason: str
    createdAt: str
    usageAssurance: NotRequired[dict[str, Any]]


class FinalizationProof(FinalizationProofBody):
    """Persisted final proof including its canonical body digest."""

    bodyDigest: str


FinalAuditVerdict = Literal["ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"]


class FinalAuditOutcomeValidation(TypedDict):
    """Result of validate_final_audit_outcome_report, including refusals.

    A failed validation can echo an unsupported verdict, so this field remains
    str even though an applied outcome has the closed FinalAuditVerdict type.
    """

    schemaVersion: Literal["agent-final-audit-outcome-validation.v1"]
    status: Literal["PASS", "FAIL"]
    verdict: str
    taskIds: list[str]
    findingIds: list[str]
    blockers: list[dict[str, Any]]
    validationDigest: str


class FinalAuditOutcomeBody(TypedDict):
    """Applied outcome body, including the runtime's explicit null artifacts."""

    schemaVersion: Literal["agent-final-audit-outcome.v1"]
    status: Literal["PASS"]
    verdict: FinalAuditVerdict
    runId: str
    packageId: str
    planRevision: int
    planDigest: str
    sourceRevision: str
    finalAudit: dict[str, Any]
    taskIds: list[str]
    findingIds: list[str]
    validation: FinalAuditOutcomeValidation
    blocker: dict[str, Any] | None
    contractChangeRequest: dict[str, Any] | None
    productionPromotionClaimed: Literal[False]
    reason: str
    appliedAt: str


class FinalAuditOutcome(FinalAuditOutcomeBody):
    """Persisted audit decision; it is not a production-promotion claim."""

    outcomeDigest: str
