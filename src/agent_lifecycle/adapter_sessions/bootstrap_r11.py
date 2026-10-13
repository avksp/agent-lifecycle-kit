"""R11 source-review preparation and durable attempt-result storage."""

from __future__ import annotations

import ast
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.adapter_sessions.attempt_authority import (
    capture_attempt_authority, _current_authority, verify_attempt_reservation, claim_attempt_start, record_uncertain_attempt, require_positive_attempt_result, _read, _write, _intent, reserve_attempt_result, _reservation, _positive_receipts, publish_attempt_result, read_attempt_result, _ROOT, _RESERVATION, _TERMINAL, _PENDING, _DISPATCH, _IDENTITY, _SOURCES,
)
from agent_lifecycle.contracts.authority_io import normalize_authority_path, read_authority_bytes
from agent_lifecycle.contracts.bounded_json import (
    load_bounded_json as _r11_json, matches_closed_schema as _r11_role_schema_matches,
)

# Compatibility exports for existing callers and retained wire decoders.
from agent_lifecycle.accounting.declared_ledger_records import (
    _R11_ROLE_CONTRACT_SHA256, _R11_COORDINATOR_BASE, _r11_role_identity, _r11_role_subject, _r11_transport_binding, _r11_cost_reservation, _r11_role_funding_record, _r11_role_prefix_record, _require,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _R11_VALIDATION_ROOTS, _R11_REVIEW_ROOT, _r11_git, capture_review_validation_sources, _r11_review_private, _r11_worker_directory, _r11_worker_sources, _r11_worker_disposition, read_source_review_worker, _r11_cost_worker, _r11_role_cost_chain, _r11_coordinator_root,
)
from agent_lifecycle.accounting.declared_ledger import (
    _R11_COORDINATOR_HEAD, _R11_COORDINATOR_SEED, _R11_COORDINATOR_SEED_SHA, _r11_coordinator_head_value, _r11_global_role_prefixes, _r11_coordinator_source, _r11_coordinator_head_bytes, _r11_coordinator_transition, read_coordinator_cost_head, advance_coordinator_cost_head, _sync_directory,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_role_authority,
    _r11_role_material_authority,
    _r11_wip,
    _r11_python_index,
    _r11_imports,
    _r11_ranges,
    _r11_coverage_rows,
    _r11_coverage_contains,
    _r11_interaction_requirements,
    _r11_required_interaction_scopes,
    _r11_utc,
    _r11_notification_envelope,
    _r11_bind_request,
    _r11_fresh_start,
    _r11_review_directory,
    collect_source_review_evidence,
    _exchange_source_review_rpc,
    _run_source_review_app_server_worker,
    _supervise_source_review_worker,
    _r11_cost_assignment_path,
    prepare_source_review_inventory,
    _r11_read_live_dispatch,
    _r11_seal_live_dispatch,
    _r11_write_role_request_files,
    _r11_role_original_deadline,
    _r11_role_request_seal,
    seal_source_review_request,
    reserve_source_review_cost,
    settle_source_review_cost,
    _supervise_costed_source_review_worker,
    finalize_source_review_assignment,
    collect_source_review_accounted_evidence,
    collect_source_review_host,
    collect_source_review_supervised_evidence,
    publish_source_review_cost_prefix,
    admit_source_review_funding,
    import_source_review_opening,
    collect_source_review_origin_bound_evidence,
    capture_source_review_catalog,
    _r11_source_review_catalog_fit,
    _prepare_source_review_role_thread,
    _r11_thread_preparation_basis,
    _run_source_review_thread_preparation,
    prepare_source_review_threads,
    collect_source_review_threads,
    _r11_assignment_thread_preparation,
    _r11_closed_worker_funding,
    collect_source_review_producer,
    collect_source_review_shared,
    collect_source_review_qualified_evidence,
    publish_source_review_composite,
    read_source_review_composite,
    install_source_review_composite,
    _r11_fresh_deadline,
    _r11_fresh_exchange,
    require_source_review_fresh_gate,
    verify_source_review_fresh_gate,
    prepare_source_review_worker,
    _run_fixed_source_review_worker,
    _supervise_fixed_source_review_worker,
    _source_review_worker_main,
    _R11_SOURCE_ORACLE_SHA256,
    _R11_PARENT_INVENTORY_SHA256,
    _R11_PRODUCT_ROOTS,
    _R11_REQUEST_CAP,
    _R11_REVIEW_RESERVE,
    _R11_REVIEW_SCHEMA_SHA256,
    _R11_REVIEW_INSTRUCTION,
    _R11_SUPPORT_ORACLE_SHA256,
    _R11_TRANSPORT_RECORD_CAP,
    _R11_PARENT_PROVENANCE_SHA256,
    _R11_PARENT_ARCHIVE,
    _R11_FIXED_WORKER,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    _r11_source_inputs,
    collect_source_partition,
    collect_source_dependencies,
    _r11_source_material,
    _r11_read_parent_file,
    _r11_parent_snapshot,
    collect_source_review_parent,
    _r11_review_parent_sources,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_body,
    _r11_role_source_content,
    _r11_role_call_index,
    _r11_role_project_calls,
    _r11_role_source_projection,
    _r11_role_shared_view_candidate,
    _r11_role_wire_request,
    _r11_role_source_exposure,
    _r11_role_request_candidate,
    _r11_role_envelope_fit,
    _r11_role_source_basis,
    _r11_validate_coverage,
    _r11_shard_request,
    _r11_role_integration_closure,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_support_authority,
    _r11_private_support,
    _r11_observe_test_rosters,
    _r11_match_test_support,
    _r11_match_cost_opening,
    collect_source_review_support,
    _R11AppServerPipe,
    _r11_host_snapshot,
    _r11_host_records,
    _r11_match_host_prelude,
    _r11_empty_thread_exchange,
    _R11PreparationReplay,
)
from agent_lifecycle.adapter_sessions.source_review_transcript import (
    verify_source_review_body_and_reads,
    SourceReviewTranscript,
    verify_source_review_transport_records,
    _r11_transcript_snapshot,
    _r11_reassemble_transcript,
    collect_source_review_transport,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_review_authorities,
    _r11_reconstruct_review_basis,
    _r11_review_cost_basis,
    _r11_cost_files,
    read_source_review_cost,
    _r11_read_role_request_files,
    _r11_role_request_origin,
    read_source_review_request,
    _r11_role_funding_origin,
    read_source_review_opening_origin,
    _r11_catalog_value,
    read_source_review_catalog,
    _r11_require_fresh_review_catalog,
    _r11_role_operation_start,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    read_source_review_envelope_fit,
    build_source_review_shards,
    reconstruct_source_review,
    _r11_role_send_basis,
    _r11_cost_before_start,
    _r11_completed_assignment,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_role_thread_preparation_basis,
    _r11_role_metadata_before_start,
    _r11_read_thread_preparation_input,
    _r11_composite_inventory,
    _r11_composite_schema,
    _r11_composite_verified,
    _r11_lead_summary,
    _r11_native_composite,
    _r11_native_task,
    _r11_fresh_operation,
    _r11_fresh_basis,
    _r11_read_fresh_input,
    _r11_fixed_worker_basis,
    _r11_read_fixed_worker_input,
    _r11_fixed_supervisor_reservation,
    _r11_live_supervisor,
)


# Immutable r362 inputs, not a positive verdict or authority to start a child.


# This pin authorizes only the reviewed role contract, never an actual model
# start or a native task. Superseded v5 execution entries refuse explicitly.


if __name__ == '__main__':
    # Import the canonical package so relative worker imports resolve identically
    # when the supervisor executes this exact source path with Python -B.
    from agent_lifecycle.adapter_sessions.bootstrap_r11 import _source_review_worker_main as _fixed_main
    raise SystemExit(_fixed_main(sys.argv[1:]))
