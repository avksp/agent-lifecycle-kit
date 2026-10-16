"""R11 source-review preparation and durable attempt-result storage."""

from __future__ import annotations

import ast as ast
import base64 as base64
import hashlib as hashlib
import json as json
import os as os
import re as re
import shlex as shlex
import stat as stat
import subprocess as subprocess
import sys
import time as time
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from datetime import timezone as timezone
from pathlib import Path as Path
from typing import Any as Any

from agent_lifecycle.accounting.declared_ledger import (
    _R11_COORDINATOR_HEAD as _R11_COORDINATOR_HEAD,
)
from agent_lifecycle.accounting.declared_ledger import (
    _R11_COORDINATOR_SEED as _R11_COORDINATOR_SEED,
)
from agent_lifecycle.accounting.declared_ledger import (
    _R11_COORDINATOR_SEED_SHA as _R11_COORDINATOR_SEED_SHA,
)
from agent_lifecycle.accounting.declared_ledger import (
    _r11_coordinator_head_bytes as _r11_coordinator_head_bytes,
)
from agent_lifecycle.accounting.declared_ledger import (
    _r11_coordinator_head_value as _r11_coordinator_head_value,
)
from agent_lifecycle.accounting.declared_ledger import (
    _r11_coordinator_source as _r11_coordinator_source,
)
from agent_lifecycle.accounting.declared_ledger import (
    _r11_coordinator_transition as _r11_coordinator_transition,
)
from agent_lifecycle.accounting.declared_ledger import (
    _r11_global_role_prefixes as _r11_global_role_prefixes,
)
from agent_lifecycle.accounting.declared_ledger import (
    _sync_directory as _sync_directory,
)
from agent_lifecycle.accounting.declared_ledger import (
    advance_coordinator_cost_head as advance_coordinator_cost_head,
)
from agent_lifecycle.accounting.declared_ledger import (
    read_coordinator_cost_head as read_coordinator_cost_head,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _R11_REVIEW_ROOT as _R11_REVIEW_ROOT,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _R11_VALIDATION_ROOTS as _R11_VALIDATION_ROOTS,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_coordinator_root as _r11_coordinator_root,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_cost_worker as _r11_cost_worker,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_git as _r11_git,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_review_private as _r11_review_private,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_role_cost_chain as _r11_role_cost_chain,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_worker_directory as _r11_worker_directory,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_worker_disposition as _r11_worker_disposition,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _r11_worker_sources as _r11_worker_sources,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    capture_review_validation_sources as capture_review_validation_sources,
)
from agent_lifecycle.accounting.declared_ledger_legacy import (
    read_source_review_worker as read_source_review_worker,
)

# Compatibility exports for existing callers and retained wire decoders.
from agent_lifecycle.accounting.declared_ledger_records import (
    _R11_COORDINATOR_BASE as _R11_COORDINATOR_BASE,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _R11_ROLE_CONTRACT_SHA256 as _R11_ROLE_CONTRACT_SHA256,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _r11_cost_reservation as _r11_cost_reservation,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _r11_role_funding_record as _r11_role_funding_record,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _r11_role_identity as _r11_role_identity,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _r11_role_prefix_record as _r11_role_prefix_record,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _r11_role_subject as _r11_role_subject,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _r11_transport_binding as _r11_transport_binding,
)
from agent_lifecycle.accounting.declared_ledger_records import (
    _require as _require,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _DISPATCH as _DISPATCH,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _IDENTITY as _IDENTITY,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _PENDING as _PENDING,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _RESERVATION as _RESERVATION,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _ROOT as _ROOT,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _SOURCES as _SOURCES,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _TERMINAL as _TERMINAL,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _current_authority as _current_authority,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _intent as _intent,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _positive_receipts as _positive_receipts,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _read as _read,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _reservation as _reservation,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _write as _write,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    capture_attempt_authority as capture_attempt_authority,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    claim_attempt_start as claim_attempt_start,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    publish_attempt_result as publish_attempt_result,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    read_attempt_result as read_attempt_result,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    record_uncertain_attempt as record_uncertain_attempt,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    require_positive_attempt_result as require_positive_attempt_result,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    reserve_attempt_result as reserve_attempt_result,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    verify_attempt_reservation as verify_attempt_reservation,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_FIXED_WORKER as _R11_FIXED_WORKER,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_PARENT_ARCHIVE as _R11_PARENT_ARCHIVE,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_PARENT_INVENTORY_SHA256 as _R11_PARENT_INVENTORY_SHA256,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_PARENT_PROVENANCE_SHA256 as _R11_PARENT_PROVENANCE_SHA256,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_PRODUCT_ROOTS as _R11_PRODUCT_ROOTS,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_REQUEST_CAP as _R11_REQUEST_CAP,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_REVIEW_INSTRUCTION as _R11_REVIEW_INSTRUCTION,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_REVIEW_RESERVE as _R11_REVIEW_RESERVE,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_REVIEW_SCHEMA_SHA256 as _R11_REVIEW_SCHEMA_SHA256,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_SOURCE_ORACLE_SHA256 as _R11_SOURCE_ORACLE_SHA256,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_SUPPORT_ORACLE_SHA256 as _R11_SUPPORT_ORACLE_SHA256,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_TRANSPORT_RECORD_CAP as _R11_TRANSPORT_RECORD_CAP,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _exchange_source_review_rpc as _exchange_source_review_rpc,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _prepare_source_review_role_thread as _prepare_source_review_role_thread,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_assignment_thread_preparation as _r11_assignment_thread_preparation,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_bind_request as _r11_bind_request,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_closed_worker_funding as _r11_closed_worker_funding,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_cost_assignment_path as _r11_cost_assignment_path,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_coverage_contains as _r11_coverage_contains,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_coverage_rows as _r11_coverage_rows,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_fresh_deadline as _r11_fresh_deadline,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_fresh_exchange as _r11_fresh_exchange,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_fresh_start as _r11_fresh_start,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_imports as _r11_imports,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_interaction_requirements as _r11_interaction_requirements,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_notification_envelope as _r11_notification_envelope,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_python_index as _r11_python_index,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_ranges as _r11_ranges,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_read_live_dispatch as _r11_read_live_dispatch,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_required_interaction_scopes as _r11_required_interaction_scopes,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_review_directory as _r11_review_directory,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_role_authority as _r11_role_authority,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_role_material_authority as _r11_role_material_authority,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_role_original_deadline as _r11_role_original_deadline,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_role_request_seal as _r11_role_request_seal,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_seal_live_dispatch as _r11_seal_live_dispatch,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_source_review_catalog_fit as _r11_source_review_catalog_fit,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_thread_preparation_basis as _r11_thread_preparation_basis,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_utc as _r11_utc,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_wip as _r11_wip,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _r11_write_role_request_files as _r11_write_role_request_files,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _run_fixed_source_review_worker as _run_fixed_source_review_worker,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _run_source_review_app_server_worker as _run_source_review_app_server_worker,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _run_source_review_thread_preparation as _run_source_review_thread_preparation,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _source_review_worker_main as _source_review_worker_main,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _supervise_costed_source_review_worker as _supervise_costed_source_review_worker,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _supervise_fixed_source_review_worker as _supervise_fixed_source_review_worker,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _supervise_source_review_worker as _supervise_source_review_worker,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    admit_source_review_funding as admit_source_review_funding,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    capture_source_review_catalog as capture_source_review_catalog,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_accounted_evidence as collect_source_review_accounted_evidence,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_evidence as collect_source_review_evidence,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_host as collect_source_review_host,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_origin_bound_evidence as collect_source_review_origin_bound_evidence,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_producer as collect_source_review_producer,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_qualified_evidence as collect_source_review_qualified_evidence,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_shared as collect_source_review_shared,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_supervised_evidence as collect_source_review_supervised_evidence,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    collect_source_review_threads as collect_source_review_threads,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    finalize_source_review_assignment as finalize_source_review_assignment,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    import_source_review_opening as import_source_review_opening,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    install_source_review_composite as install_source_review_composite,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    prepare_source_review_inventory as prepare_source_review_inventory,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    prepare_source_review_threads as prepare_source_review_threads,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    prepare_source_review_worker as prepare_source_review_worker,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    publish_source_review_composite as publish_source_review_composite,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    publish_source_review_cost_prefix as publish_source_review_cost_prefix,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    read_source_review_composite as read_source_review_composite,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    require_source_review_fresh_gate as require_source_review_fresh_gate,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    reserve_source_review_cost as reserve_source_review_cost,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    seal_source_review_request as seal_source_review_request,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    settle_source_review_cost as settle_source_review_cost,
)
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    verify_source_review_fresh_gate as verify_source_review_fresh_gate,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_catalog_value as _r11_catalog_value,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_cost_files as _r11_cost_files,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_read_role_request_files as _r11_read_role_request_files,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_reconstruct_review_basis as _r11_reconstruct_review_basis,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_require_fresh_review_catalog as _r11_require_fresh_review_catalog,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_review_authorities as _r11_review_authorities,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_review_cost_basis as _r11_review_cost_basis,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_role_funding_origin as _r11_role_funding_origin,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_role_operation_start as _r11_role_operation_start,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_role_request_origin as _r11_role_request_origin,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    read_source_review_catalog as read_source_review_catalog,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    read_source_review_cost as read_source_review_cost,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    read_source_review_opening_origin as read_source_review_opening_origin,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    read_source_review_request as read_source_review_request,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    _r11_parent_snapshot as _r11_parent_snapshot,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    _r11_read_parent_file as _r11_read_parent_file,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    _r11_review_parent_sources as _r11_review_parent_sources,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    _r11_source_inputs as _r11_source_inputs,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    _r11_source_material as _r11_source_material,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    collect_source_dependencies as collect_source_dependencies,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    collect_source_partition as collect_source_partition,
)
from agent_lifecycle.adapter_sessions.source_review_inputs import (
    collect_source_review_parent as collect_source_review_parent,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_composite_inventory as _r11_composite_inventory,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_composite_schema as _r11_composite_schema,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_composite_verified as _r11_composite_verified,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_fixed_supervisor_reservation as _r11_fixed_supervisor_reservation,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_fixed_worker_basis as _r11_fixed_worker_basis,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_fresh_basis as _r11_fresh_basis,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_fresh_operation as _r11_fresh_operation,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_lead_summary as _r11_lead_summary,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_live_supervisor as _r11_live_supervisor,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_native_composite as _r11_native_composite,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_native_task as _r11_native_task,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_read_fixed_worker_input as _r11_read_fixed_worker_input,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_read_fresh_input as _r11_read_fresh_input,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_read_thread_preparation_input as _r11_read_thread_preparation_input,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_role_metadata_before_start as _r11_role_metadata_before_start,
)
from agent_lifecycle.adapter_sessions.source_review_preparation_records import (
    _r11_role_thread_preparation_basis as _r11_role_thread_preparation_basis,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_body as _r11_role_body,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_call_index as _r11_role_call_index,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_envelope_fit as _r11_role_envelope_fit,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_integration_closure as _r11_role_integration_closure,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_project_calls as _r11_role_project_calls,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_request_candidate as _r11_role_request_candidate,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_shared_view_candidate as _r11_role_shared_view_candidate,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_source_basis as _r11_role_source_basis,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_source_content as _r11_role_source_content,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_source_exposure as _r11_role_source_exposure,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_source_projection as _r11_role_source_projection,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_role_wire_request as _r11_role_wire_request,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_shard_request as _r11_shard_request,
)
from agent_lifecycle.adapter_sessions.source_review_roles import (
    _r11_validate_coverage as _r11_validate_coverage,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    _r11_completed_assignment as _r11_completed_assignment,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    _r11_cost_before_start as _r11_cost_before_start,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    _r11_role_send_basis as _r11_role_send_basis,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    build_source_review_shards as build_source_review_shards,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    read_source_review_envelope_fit as read_source_review_envelope_fit,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    reconstruct_source_review as reconstruct_source_review,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_empty_thread_exchange as _r11_empty_thread_exchange,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_host_records as _r11_host_records,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_host_snapshot as _r11_host_snapshot,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_match_cost_opening as _r11_match_cost_opening,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_match_host_prelude as _r11_match_host_prelude,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_match_test_support as _r11_match_test_support,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_observe_test_rosters as _r11_observe_test_rosters,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_private_support as _r11_private_support,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _r11_support_authority as _r11_support_authority,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _R11AppServerPipe as _R11AppServerPipe,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    _R11PreparationReplay as _R11PreparationReplay,
)
from agent_lifecycle.adapter_sessions.source_review_support import (
    collect_source_review_support as collect_source_review_support,
)
from agent_lifecycle.adapter_sessions.source_review_transcript import (
    SourceReviewTranscript as SourceReviewTranscript,
)
from agent_lifecycle.adapter_sessions.source_review_transcript import (
    _r11_reassemble_transcript as _r11_reassemble_transcript,
)
from agent_lifecycle.adapter_sessions.source_review_transcript import (
    _r11_transcript_snapshot as _r11_transcript_snapshot,
)
from agent_lifecycle.adapter_sessions.source_review_transcript import (
    collect_source_review_transport as collect_source_review_transport,
)
from agent_lifecycle.adapter_sessions.source_review_transcript import (
    verify_source_review_body_and_reads as verify_source_review_body_and_reads,
)
from agent_lifecycle.adapter_sessions.source_review_transcript import (
    verify_source_review_transport_records as verify_source_review_transport_records,
)
from agent_lifecycle.contracts import LifecycleError as LifecycleError
from agent_lifecycle.contracts import canonical_bytes as canonical_bytes
from agent_lifecycle.contracts import canonical_digest as canonical_digest
from agent_lifecycle.contracts.authority_io import normalize_authority_path as normalize_authority_path
from agent_lifecycle.contracts.authority_io import read_authority_bytes as read_authority_bytes
from agent_lifecycle.contracts.bounded_json import (
    load_bounded_json as _r11_json,
)
from agent_lifecycle.contracts.bounded_json import (
    matches_closed_schema as _r11_role_schema_matches,
)

_COMPATIBILITY_IMPORTS = (_r11_json, _r11_role_schema_matches)

# Immutable r362 inputs, not a positive verdict or authority to start a child.


# This pin authorizes only the reviewed role contract, never an actual model
# start or a native task. Superseded v5 execution entries refuse explicitly.


if __name__ == "__main__":
    # Import the canonical package so relative worker imports resolve identically
    # when the supervisor executes this exact source path with Python -B.
    from agent_lifecycle.adapter_sessions.bootstrap_r11 import _source_review_worker_main as _fixed_main

    raise SystemExit(_fixed_main(sys.argv[1:]))
