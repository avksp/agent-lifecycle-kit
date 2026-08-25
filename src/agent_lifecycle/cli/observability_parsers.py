"""Parser declarations for read-only observability commands."""

from __future__ import annotations

import argparse


def _add_report_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    report = subparsers.add_parser("report", help="read-only report commands")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    status_view = report_sub.add_parser("status-view")
    status_view.add_argument("--project-root", default=".")
    status_view.add_argument("--artifact", action="append", default=[])
    status_view.add_argument("--max-items", type=int, default=12)
    status_view.add_argument("--target-window", default="8k")
    status_view.add_argument("--out")
    event_feed = report_sub.add_parser("event-feed")
    event_feed.add_argument("--state", required=True)
    event_feed.add_argument("--out")
    multi_run = report_sub.add_parser("multi-run", aliases=["attention"])
    multi_run.add_argument("--project-root", default=".")
    multi_run.add_argument("--run-root", "--run", dest="run_root", action="append", default=[])
    multi_run.add_argument("--max-runs", type=int, default=32)
    multi_run.add_argument("--max-bytes-per-run", type=int, default=1_048_576)
    multi_run.add_argument("--stale-after-seconds", type=int, default=86_400)
    multi_run.add_argument("--now")
    multi_run.add_argument("--out")
    progress = report_sub.add_parser("progress")
    progress.add_argument("--state", required=True)
    progress.add_argument("--usage-receipt", action="append", default=[])
    progress.add_argument("--change-summary")
    progress.add_argument("--watch", action="store_true")
    progress.add_argument("--watch-iterations", type=int, default=5)
    progress.add_argument("--watch-interval", type=float, default=1.0)
    progress.add_argument("--terminal", action="store_true")
    progress.add_argument("--out")
    progress_bridge = report_sub.add_parser("progress-bridge")
    progress_bridge.add_argument("--adapter", required=True)
    progress_bridge.add_argument("--support-level", choices=["AUTO", "WATCH", "MANUAL", "UNSUPPORTED"], required=True)
    progress_bridge.add_argument(
        "--hook-point",
        choices=[
            "after-workflow-run",
            "after-task-result",
            "after-task-accept",
            "after-finalize",
            "side-terminal-watch",
            "manual",
        ],
        required=True,
    )
    progress_bridge.add_argument("--state", required=True)
    progress_bridge.add_argument("--usage-receipt", action="append", default=[])
    progress_bridge.add_argument("--change-summary")
    progress_bridge.add_argument("--display-mode", choices=["terminal", "json"], default="terminal")
    progress_bridge.add_argument("--watch", action="store_true")
    progress_bridge.add_argument("--watch-iterations", type=int, default=1)
    progress_bridge.add_argument("--watch-interval", type=float, default=0.0)
    progress_bridge.add_argument("--terminal", action="store_true")
    progress_bridge.add_argument("--out")
    change_summary = report_sub.add_parser("change-summary")
    change_summary.add_argument("--project-root", default=".")
    change_summary.add_argument("--base")
    change_summary.add_argument("--head")
    change_summary.add_argument("--staged", action="store_true")
    change_summary.add_argument("--path", action="append", default=[])
    change_summary.add_argument("--out")
    security = report_sub.add_parser("security-analysis")
    security.add_argument("--finding", action="append", default=[])
    security.add_argument("--source-revision")
    security.add_argument("--expected-source-revision")
    security.add_argument("--profile", action="store_true")
    security.add_argument("--out")
