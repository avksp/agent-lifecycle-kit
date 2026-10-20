"""Parser declarations for lifecycle and project execution commands."""

from __future__ import annotations

import argparse

from agent_lifecycle.adapter_sessions import START_MODES
from agent_lifecycle.cli.progress_hooks import add_progress_hook_args
from agent_lifecycle.cli.project import add_project_parser
from agent_lifecycle.cli.workflow_task_parsers import add_strategy_adoption_args, add_workflow_task_parsers
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS
from agent_lifecycle.resources import builtin_profile_path
from agent_lifecycle.review_mesh.operator_templates import REVIEW_MESH_OPERATOR_TEMPLATE_IDS
from agent_lifecycle.workflow.closing_window import ORDINARY_OPERATOR_CLAIM, PROTECTED_OPERATOR_CLAIM

_add_project_parser = add_project_parser

_BASELINE_PROFILE = builtin_profile_path("lifecycle-baselines.v1.json")
_MODEL_ROUTING_PROFILE = builtin_profile_path("model-routing-profile.v1.json")
_RISK_POLICY = builtin_profile_path("risk-execution-policy.v1.json")
_SMALL_CONTEXT_PROFILE = builtin_profile_path("small-context-profile.v1.json")


def _add_operator_claim_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--requested-claim",
        choices=[ORDINARY_OPERATOR_CLAIM, PROTECTED_OPERATOR_CLAIM],
        help="request an ordinary or protected operator route; unavailable protected routes refuse",
    )


def _add_start_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    start = subparsers.add_parser("start", help="start or resume an ALK lifecycle action")
    start.add_argument("--adapter")
    action = start.add_mutually_exclusive_group(required=True)
    action.add_argument("--file", "--task-file", dest="task_file")
    action.add_argument("--text", "--task-text", dest="task_text")
    action.add_argument("--resume", dest="resume_session_id")
    start.add_argument("--mode", choices=list(START_MODES), default="auto")
    start.add_argument("--risk", choices=["auto", "S0", "S1", "S2"], default="auto")
    start.add_argument("--risk-policy", default=_RISK_POLICY)
    start.add_argument("--routing-profile", default=_MODEL_ROUTING_PROFILE)
    start.add_argument("--baseline-profile", default=_BASELINE_PROFILE)
    start.add_argument("--host-model-profile")
    start.add_argument(
        "--launch",
        action="store_true",
        help="explicitly launch a qualified planning host or frozen managed task",
    )
    start.add_argument(
        "--host-launch-profile",
        help="operator-local profile; planning defaults to .alk/host-launch/<adapter>.json",
    )
    start.add_argument("--risk-profile-out")
    start.add_argument("--strategy-out")
    start.add_argument("--descriptor")
    start.add_argument("--session-root")
    start.add_argument("--state")
    start.add_argument("--lock")
    start.add_argument("--task")
    start.add_argument("--operation-id")
    start.add_argument("--expected-revision", type=int)
    start.add_argument("--source-revision")
    start.add_argument("--candidate-out")
    start.add_argument("--package-id", default="unified-start")
    start.add_argument("--max-input-bytes", type=int, default=32768)
    start.add_argument("--target-tokens", type=int, default=4096)
    start.add_argument("--out")
    start.add_argument("--project-profile")
    start.add_argument("--no-project-profile", action="store_true")
    start.add_argument(
        "--preset",
        help="apply a built-in workflow preset below explicit project-profile settings",
    )


def _add_host_launch_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    host_launch = subparsers.add_parser("host-launch", help="inspect or preflight an operator-local host profile")
    host_launch_sub = host_launch.add_subparsers(dest="host_launch_command", required=True)
    for command in ("inspect", "preflight"):
        child = host_launch_sub.add_parser(command)
        child.add_argument("--profile", required=True)
        child.add_argument("--out")
        if command == "preflight":
            child.add_argument("--accounting-request", help="refuse unqualified accounting requests before probing")
    accounting = host_launch_sub.add_parser("accounting-check", help="check accounting input; pending evidence refuses")
    for flag in ("profile", "request", "expectation-digest", "plan-digest", "candidate-digest"):
        accounting.add_argument("--" + flag, required=True)
    accounting.add_argument("--out")
    qualification = host_launch_sub.add_parser("qualification-check", help="check staged source-only qualification")
    qualification.add_argument("--profiles-root", required=True)
    qualification.add_argument("--adapter", required=True)
    qualification.add_argument("--request", required=True)
    qualification.add_argument("--out")


def _add_schema_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    schema = subparsers.add_parser("schema", help="inspect bundled JSON schemas")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    schema_list = schema_sub.add_parser("list")
    schema_list.add_argument("--scope", choices=["all", "core"], default="all")
    show = schema_sub.add_parser("show")
    show.add_argument("schema_id")


def _add_review_mesh_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    review_mesh = subparsers.add_parser("review-mesh", help="optional Review Mesh commands")
    review_mesh_sub = review_mesh.add_subparsers(dest="review_mesh_command", required=True)
    template_list = review_mesh_sub.add_parser("template-list")
    template_list.add_argument("--out")
    profile = review_mesh_sub.add_parser("profile")
    profile.add_argument("--profile-id", default="optional-review-mesh")
    profile.add_argument("--mode", choices=list(REVIEW_MESH_MODE_IDS), action="append", default=[])
    profile.add_argument("--default-mode", choices=list(REVIEW_MESH_MODE_IDS), default="leader-draft-multi-review")
    profile.add_argument("--reviewer-model-class", action="append", default=[])
    profile.add_argument("--require-independence", action="store_true")
    profile.add_argument("--independence-dimension", choices=["host", "model"], action="append", default=[])
    profile.add_argument("--allow-live-calls", action="store_true")
    profile.add_argument("--max-invocations", type=int)
    profile.add_argument("--max-input-tokens", type=int)
    profile.add_argument("--max-output-tokens", type=int)
    profile.add_argument("--max-wall-seconds", type=int)
    profile.add_argument("--out")
    recommend = review_mesh_sub.add_parser("recommend")
    source = recommend.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--file")
    source.add_argument("--intake")
    source.add_argument("--manifest")
    recommend.add_argument("--sdd-tier", choices=["S0", "S1", "S2"])
    recommend.add_argument("--risk-flag", action="append", default=[])
    recommend.add_argument("--out")
    prepare = review_mesh_sub.add_parser("prepare")
    prepare_source = prepare.add_mutually_exclusive_group(required=True)
    prepare_source.add_argument("--manifest")
    prepare_source.add_argument("--intake")
    prepare_source.add_argument("--handoff")
    prepare.add_argument("--template", choices=list(REVIEW_MESH_OPERATOR_TEMPLATE_IDS), default="leader-draft-review")
    prepare.add_argument("--profile-id")
    prepare.add_argument("--phase")
    prepare.add_argument("--reviewer", action="append", default=[])
    prepare.add_argument("--blocking", action="store_true")
    prepare.add_argument("--evidence-id", action="append", default=[])
    prepare.add_argument("--out-dir")
    prepare.add_argument("--out")
    prepare.add_argument("--review-input", help="explicit source-bound portable reading inventory")
    prepare.add_argument("--repository-root", default=".")
    assign = review_mesh_sub.add_parser("assign")
    assign_source = assign.add_mutually_exclusive_group(required=True)
    assign_source.add_argument("--manifest")
    assign_source.add_argument("--intake")
    assign_source.add_argument("--handoff")
    assign.add_argument("--profile")
    assign.add_argument("--mode", choices=list(REVIEW_MESH_MODE_IDS), required=True)
    assign.add_argument("--phase", required=True)
    assign.add_argument("--assignment-id", required=True)
    assign.add_argument("--reviewer-id", required=True)
    assign.add_argument("--reviewer-role", default="reviewer")
    assign.add_argument("--reviewer-model-class", default="strong-reasoning")
    assign.add_argument("--reviewer-host-identity-hash")
    assign.add_argument("--reviewer-model-identity-hash")
    assign.add_argument("--blocking", action="store_true")
    assign.add_argument("--evidence-id", action="append", default=[])
    assign.add_argument("--out")
    import_result = review_mesh_sub.add_parser("import-result")
    import_result.add_argument("--profile", required=True)
    import_result.add_argument("--assignment", required=True)
    import_result.add_argument("--reviewer-output", required=True)
    import_result.add_argument("--allow-local-evidence-ref", action="store_true")
    import_result.add_argument("--out")
    synthesize = review_mesh_sub.add_parser("synthesize")
    synthesize.add_argument("--profile", required=True)
    synthesize.add_argument("--result", action="append", required=True)
    synthesize.add_argument("--mode", choices=list(REVIEW_MESH_MODE_IDS))
    synthesize.add_argument("--accepted-finding-id", action="append", default=[])
    synthesize.add_argument("--rejected-finding-id", action="append", default=[])
    synthesize.add_argument("--out")
    quorum = review_mesh_sub.add_parser("quorum")
    quorum.add_argument("--profile", required=True)
    quorum.add_argument("--synthesis", required=True)
    quorum.add_argument("--min-reviewers", type=int, required=True)
    quorum.add_argument("--required-role", action="append", default=[])
    quorum.add_argument("--reviewer-role", action="append", default=[])
    quorum.add_argument("--out")


def _add_workflow_continue_parser(
    workflow_sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    workflow_continue = workflow_sub.add_parser(
        "continue",
        help="project or explicitly apply existing authoritative workflow transitions",
    )
    workflow_continue.add_argument("--state", required=True)
    _add_operator_claim_argument(workflow_continue)
    workflow_continue.add_argument("--manifest", required=True)
    workflow_continue.add_argument("--lock")
    workflow_continue.add_argument("--operation-id")
    workflow_continue.add_argument("--expected-revision", required=True, type=int)
    workflow_continue.add_argument("--source-revision", required=True)
    workflow_continue.add_argument("--reason", required=True)
    workflow_continue.add_argument("--apply", action="store_true")
    workflow_continue.add_argument("--until-blocked", action="store_true")
    workflow_continue.add_argument("--local-only", action="store_true")
    workflow_continue.add_argument("--input-bundle")
    workflow_continue.add_argument("--max-transitions", type=int)
    workflow_continue.add_argument("--max-io-bytes", type=int)
    workflow_continue.add_argument("--resume-receipt")
    workflow_continue.add_argument("--projected-state-revision", type=int)
    workflow_continue.add_argument("--projected-action-digest")
    workflow_continue.add_argument("--task")
    workflow_continue.add_argument("--authorization-receipt")
    workflow_continue.add_argument("--risk-profile")
    add_strategy_adoption_args(workflow_continue)
    workflow_continue.add_argument("--result")
    workflow_continue.add_argument("--model-usage-receipt")
    workflow_continue.add_argument("--budget-targets")
    workflow_continue.add_argument("--review")
    workflow_continue.add_argument("--implementation-audit")
    workflow_continue.add_argument("--finding-id", action="append", default=[])
    workflow_continue.add_argument("--final-audit")
    workflow_continue.add_argument(
        "--verdict",
        choices=["ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"],
    )
    workflow_continue.add_argument("--task-id", action="append", default=[])
    workflow_continue.add_argument("--proof")
    workflow_continue.add_argument("--proof-integrity")
    workflow_continue.add_argument("--goal-record")
    workflow_continue.add_argument("--follow-up-register")
    workflow_continue.add_argument("--completion-gate-receipt")
    workflow_continue.add_argument("--final-implementation-audit")
    workflow_continue.add_argument("--review-mesh-quorum", action="append", default=[])
    workflow_continue.add_argument("--out")


def _add_workflow_state_parsers(
    workflow_sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    maintenance = workflow_sub.add_parser("maintenance", help="collect eligible closed-run raw details")
    maintenance.add_argument("--authority", required=True)
    maintenance.add_argument("--authority-sha", required=True)
    maintenance.add_argument("--candidate-limit", required=True, type=int)
    maintenance.add_argument("--deadline", required=True)
    maintenance.add_argument("--journal", dest="maintenance_journal_override", help=argparse.SUPPRESS)
    maintenance.add_argument("--private-root", dest="maintenance_root_override", help=argparse.SUPPRESS)
    workflow_init = workflow_sub.add_parser("init")
    workflow_init.add_argument("--state", required=True)
    workflow_init.add_argument("--run-id", required=True)
    workflow_init.add_argument("--package-id", required=True)
    workflow_init.add_argument("--package-root")
    workflow_init.add_argument("--event-log")
    workflow_init.add_argument("--manifest")
    workflow_init.add_argument("--source-revision")
    workflow_init.add_argument("--packet-output-dir")
    workflow_init.add_argument("--apply", action="store_true")
    workflow_init.add_argument("--projected-target-digest")
    workflow_init.add_argument("--operation-id")
    workflow_migrate = workflow_sub.add_parser("state-migrate")
    workflow_migrate.add_argument("--state", required=True)
    workflow_migrate.add_argument("--operation-id", required=True)
    workflow_migrate.add_argument("--expected-revision", required=True, type=int)
    workflow_migrate.add_argument("--source-revision", required=True)
    workflow_legacy = workflow_sub.add_parser(
        "migrate-runner-artifact",
        help="convert one legacy runner artifact into a non-authoritative archival record",
    )
    workflow_legacy.add_argument("--input", required=True)
    workflow_legacy.add_argument("--output", "--out", dest="output", required=True)
    workflow_legacy.add_argument("--expected-sha256")
    workflow_legacy.add_argument("--max-input-bytes", type=int, default=1_048_576)
    workflow_status = workflow_sub.add_parser("status")
    workflow_status.add_argument("--state", required=True)
    workflow_status.add_argument("--digest-prefix-length", type=int)
    workflow_status.add_argument("--full", action="store_true")
    workflow_next = workflow_sub.add_parser("next")
    workflow_next.add_argument("--state", required=True)
    workflow_run = workflow_sub.add_parser("run")
    workflow_run.add_argument("--state", required=True)
    workflow_run.add_argument("--manifest", required=True)
    workflow_run.add_argument("--lock")
    workflow_run.add_argument("--operation-id", required=True)
    workflow_run.add_argument("--expected-revision", required=True, type=int)
    workflow_run.add_argument("--source-revision", required=True)
    workflow_run.add_argument("--reason")
    workflow_run.add_argument("--out")
    add_progress_hook_args(workflow_run)
    _add_workflow_continue_parser(workflow_sub)
    workflow_adopt = workflow_sub.add_parser("adopt-plan")
    workflow_adopt.add_argument("--state", required=True)
    _add_operator_claim_argument(workflow_adopt)
    workflow_adopt.add_argument("--manifest", required=True)
    workflow_adopt.add_argument("--operation-id", required=True)
    workflow_adopt.add_argument("--expected-revision", required=True, type=int)
    workflow_adopt.add_argument("--source-revision", required=True)
    workflow_adopt.add_argument("--reset-tasks", action="store_true")
    workflow_adopt.add_argument("--preserve-accepted-compatible", action="store_true")
    workflow_adopt.add_argument(
        "--start-mode",
        choices=["approval-required", "auto-after-freeze", "plan-only"],
        default="approval-required",
    )
    workflow_adopt.add_argument("--authorized-by")
    workflow_run_start = workflow_sub.add_parser("run-start")
    workflow_run_start.add_argument("--state", required=True)
    workflow_run_start.add_argument("--operation-id", required=True)
    workflow_run_start.add_argument("--expected-revision", required=True, type=int)
    workflow_run_start.add_argument("--source-revision", required=True)
    workflow_run_start.add_argument("--reason", required=True)


def _add_workflow_control_parsers(
    workflow_sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    workflow_authorize = workflow_sub.add_parser("authorize")
    workflow_authorize.add_argument("--state", required=True)
    workflow_authorize.add_argument("--operation-id", required=True)
    workflow_authorize.add_argument("--expected-revision", required=True, type=int)
    workflow_authorize.add_argument("--source-revision", required=True)
    workflow_authorize.add_argument("--receipt", required=True)
    workflow_authorize.add_argument("--reason", required=True)
    workflow_external_pause = workflow_sub.add_parser("external-pause", aliases=["pause-external"])
    workflow_external_pause.add_argument("--state", required=True)
    workflow_external_pause.add_argument("--operation-id", required=True)
    workflow_external_pause.add_argument("--expected-revision", required=True, type=int)
    workflow_external_pause.add_argument("--action-id", required=True)
    workflow_external_pause.add_argument("--receipt", required=True)
    workflow_external_pause.add_argument("--reason", required=True)
    workflow_external_resume = workflow_sub.add_parser("external-resume", aliases=["resume-external"])
    workflow_external_resume.add_argument("--state", required=True)
    workflow_external_resume.add_argument("--operation-id", required=True)
    workflow_external_resume.add_argument("--expected-revision", required=True, type=int)
    workflow_external_resume.add_argument("--receipt", required=True)
    workflow_external_resume.add_argument("--reason", required=True)
    workflow_block = workflow_sub.add_parser("block")
    workflow_block.add_argument("--state", required=True)
    workflow_block.add_argument("--operation-id", required=True)
    workflow_block.add_argument("--expected-revision", required=True, type=int)
    workflow_block.add_argument("--blocker-code", required=True)
    workflow_block.add_argument("--review-task")
    workflow_block.add_argument("--reason", required=True)
    workflow_resolve = workflow_sub.add_parser("resolve")
    workflow_resolve.add_argument("--state", required=True)
    workflow_resolve.add_argument("--operation-id", required=True)
    workflow_resolve.add_argument("--expected-revision", required=True, type=int)
    workflow_resolve.add_argument("--reason", required=True)


def _add_workflow_review_parsers(
    workflow_sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    workflow_accept = workflow_sub.add_parser("task-accept")
    workflow_accept.add_argument("--state", required=True)
    workflow_accept.add_argument("--task", required=True)
    workflow_accept.add_argument("--operation-id", required=True)
    workflow_accept.add_argument("--expected-revision", required=True, type=int)
    workflow_accept.add_argument("--source-revision")
    workflow_accept.add_argument("--review", required=True)
    workflow_accept.add_argument("--implementation-audit")
    workflow_accept.add_argument("--reason", required=True)
    add_progress_hook_args(workflow_accept)
    workflow_rework = workflow_sub.add_parser("task-rework")
    workflow_rework.add_argument("--state", required=True)
    workflow_rework.add_argument("--task", required=True)
    workflow_rework.add_argument("--operation-id", required=True)
    workflow_rework.add_argument("--expected-revision", required=True, type=int)
    workflow_rework.add_argument("--source-revision", required=True)
    workflow_rework.add_argument("--review", required=True)
    workflow_rework.add_argument("--implementation-audit")
    workflow_rework.add_argument("--finding-id", action="append", default=[], required=True)
    workflow_rework.add_argument("--reason", required=True)
    workflow_outcome = workflow_sub.add_parser("task-review-apply")
    workflow_outcome.add_argument("--state", required=True)
    workflow_outcome.add_argument("--task", required=True)
    workflow_outcome.add_argument("--operation-id", required=True)
    workflow_outcome.add_argument("--expected-revision", required=True, type=int)
    workflow_outcome.add_argument("--source-revision", required=True)
    workflow_outcome.add_argument("--review", required=True)
    workflow_outcome.add_argument("--implementation-audit")
    workflow_outcome.add_argument("--finding-id", action="append", default=[])
    workflow_outcome.add_argument("--reason", required=True)
    add_progress_hook_args(workflow_outcome)
    workflow_final_outcome = workflow_sub.add_parser("final-audit-outcome")
    workflow_final_outcome.add_argument("--state", required=True)
    workflow_final_outcome.add_argument("--operation-id", required=True)
    workflow_final_outcome.add_argument("--expected-revision", required=True, type=int)
    workflow_final_outcome.add_argument("--source-revision", required=True)
    workflow_final_outcome.add_argument("--final-audit", required=True)
    workflow_final_outcome.add_argument(
        "--verdict",
        required=True,
        choices=["ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"],
    )
    workflow_final_outcome.add_argument("--task-id", action="append", default=[])
    workflow_final_outcome.add_argument("--finding-id", action="append", default=[])
    workflow_final_outcome.add_argument("--reason", required=True)
    add_progress_hook_args(workflow_final_outcome)
    workflow_finalize = workflow_sub.add_parser("finalize")
    workflow_finalize.add_argument("--state", required=True)
    _add_operator_claim_argument(workflow_finalize)
    workflow_finalize.add_argument("--operation-id", required=True)
    workflow_finalize.add_argument("--expected-revision", required=True, type=int)
    workflow_finalize.add_argument("--source-revision", required=True)
    workflow_finalize.add_argument("--final-audit", required=True)
    workflow_finalize.add_argument("--proof", required=True)
    workflow_finalize.add_argument("--proof-integrity")
    workflow_finalize.add_argument("--goal-record")
    workflow_finalize.add_argument("--follow-up-register")
    workflow_finalize.add_argument("--completion-gate-receipt")
    workflow_finalize.add_argument("--final-implementation-audit")
    workflow_finalize.add_argument("--release-full-receipt")
    workflow_finalize.add_argument("--review-mesh-quorum", action="append", default=[])
    workflow_finalize.add_argument("--reason", required=True)
    add_progress_hook_args(workflow_finalize)


def _add_workflow_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    workflow = subparsers.add_parser("workflow", help="workflow commands")
    workflow_sub = workflow.add_subparsers(dest="workflow_command", required=True)
    _add_workflow_state_parsers(workflow_sub)
    _add_workflow_control_parsers(workflow_sub)
    add_workflow_task_parsers(workflow_sub)
    _add_workflow_review_parsers(workflow_sub)
