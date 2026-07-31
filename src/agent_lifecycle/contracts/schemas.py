"""Built-in JSON schema registry for portable lifecycle envelopes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts.adapter_contract_schemas import ADAPTER_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.adapter_event_schemas import ADAPTER_EVENT_SCHEMAS
from agent_lifecycle.contracts.bug_forensics_schemas import BUG_FORENSICS_SCHEMAS
from agent_lifecycle.contracts.context_model_schemas import CONTEXT_MODEL_SCHEMAS
from agent_lifecycle.contracts.core_schemas import CORE_SCHEMAS
from agent_lifecycle.contracts.cross_check_schemas import CROSS_CHECK_SCHEMAS
from agent_lifecycle.contracts.evidence_import_schemas import EVIDENCE_IMPORT_SCHEMAS
from agent_lifecycle.contracts.host_capability_schemas import HOST_CAPABILITY_SCHEMAS
from agent_lifecycle.contracts.import_dialect_schemas import IMPORT_DIALECT_SCHEMAS
from agent_lifecycle.contracts.metric_schemas import METRIC_SCHEMAS
from agent_lifecycle.contracts.plan_contract_schemas import PLAN_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.policy_schemas import POLICY_SCHEMAS
from agent_lifecycle.contracts.proof_integrity_schemas import PROOF_INTEGRITY_SCHEMAS
from agent_lifecycle.contracts.release_contract_schemas import RELEASE_CONTRACT_SCHEMAS
from agent_lifecycle.contracts.review_quality_schemas import REVIEW_QUALITY_SCHEMAS
from agent_lifecycle.contracts.runner_worktree_schemas import RUNNER_WORKTREE_SCHEMAS
from agent_lifecycle.contracts.sandbox_schemas import SANDBOX_SCHEMAS
from agent_lifecycle.contracts.status_goal_schemas import STATUS_GOAL_SCHEMAS
from agent_lifecycle.contracts.usage_export_schemas import USAGE_EXPORT_SCHEMAS

SCHEMA_INDEX_VERSION = "agent-lifecycle-schema-index.v1"

_SCHEMA_GROUPS = (
    CORE_SCHEMAS,
    ADAPTER_EVENT_SCHEMAS,
    REVIEW_QUALITY_SCHEMAS,
    EVIDENCE_IMPORT_SCHEMAS,
    IMPORT_DIALECT_SCHEMAS,
    STATUS_GOAL_SCHEMAS,
    RUNNER_WORKTREE_SCHEMAS,
    BUG_FORENSICS_SCHEMAS,
    CROSS_CHECK_SCHEMAS,
    SANDBOX_SCHEMAS,
    HOST_CAPABILITY_SCHEMAS,
    USAGE_EXPORT_SCHEMAS,
    PROOF_INTEGRITY_SCHEMAS,
    ADAPTER_CONTRACT_SCHEMAS,
    CONTEXT_MODEL_SCHEMAS,
    RELEASE_CONTRACT_SCHEMAS,
    PLAN_CONTRACT_SCHEMAS,
    METRIC_SCHEMAS,
    POLICY_SCHEMAS,
)

_SCHEMAS: dict[str, dict[str, Any]] = {}
for _group in _SCHEMA_GROUPS:
    _overlap = set(_SCHEMAS).intersection(_group)
    if _overlap:
        raise RuntimeError(f"duplicate schema ids: {sorted(_overlap)}")
    _SCHEMAS.update(_group)


def list_schemas() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_INDEX_VERSION,
        "schemas": [
            {"id": schema_id, "draft": schema["$schema"]}
            for schema_id, schema in sorted(_SCHEMAS.items())
        ],
    }


def get_schema(schema_id: str) -> dict[str, Any]:
    if schema_id not in _SCHEMAS:
        from agent_lifecycle.contracts.errors import LifecycleError

        raise LifecycleError("unknown-schema", f"unknown schema: {schema_id}")
    return deepcopy(_SCHEMAS[schema_id])
