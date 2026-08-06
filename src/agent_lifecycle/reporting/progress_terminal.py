"""Terminal rendering for lifecycle progress receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError


def render_progress_terminal(payload: dict[str, Any], *, include_summary: bool = True) -> str:
    """Render a progress view or watch receipt as terminal text."""

    schema = payload.get("schemaVersion")
    if schema == "agent-goal-progress-view.v1":
        return render_goal_view_terminal(payload, include_summary=include_summary)
    if schema == "agent-lifecycle-progress-view.v1":
        return _render_lines(
            lines=_strings(payload.get("lines")),
            terminal_summary=_summary_line(payload.get("terminalSummary")),
            include_summary=include_summary,
        )
    if schema == "agent-lifecycle-progress-watch.v1":
        frames = payload.get("frames")
        if not isinstance(frames, list) or not frames:
            raise LifecycleError("progress-terminal-watch-empty", "progress watch receipt has no frames")
        latest = frames[-1] if isinstance(frames[-1], dict) else {}
        return _render_lines(
            lines=_strings(latest.get("lines")),
            terminal_summary=_summary_line(latest.get("terminalSummary")),
            include_summary=include_summary,
        )
    raise LifecycleError("progress-terminal-unsupported-schema", "unsupported progress receipt schema", {"schemaVersion": schema})


def render_goal_view_terminal(payload: dict[str, Any], *, include_summary: bool = True) -> str:
    """Render a goal progress view as terminal text."""

    if payload.get("schemaVersion") != "agent-goal-progress-view.v1":
        raise LifecycleError(
            "goal-view-terminal-unsupported-schema",
            "unsupported goal view receipt schema",
            {"schemaVersion": payload.get("schemaVersion")},
        )
    goal = payload.get("goal")
    lifecycle = payload.get("lifecycle")
    progress = payload.get("progress")
    metrics = payload.get("metrics")
    if (
        not isinstance(goal, dict)
        or not isinstance(lifecycle, dict)
        or not isinstance(progress, dict)
        or not isinstance(metrics, dict)
    ):
        raise LifecycleError("goal-view-terminal-invalid", "goal view receipt is missing renderable sections")
    lines = [
        f"GOAL                   {str(goal.get('goalStatus') or 'UNKNOWN'):<10} "
        f"{str(metrics.get('duration') or '00:00:00'):<8} {str(metrics.get('tokens') or '↑?/↓? tok'):<15} "
        f"{metrics.get('changeSummary') or ''}",
        f"LIFECYCLE              {str(lifecycle.get('phase') or 'UNKNOWN'):<10} "
        f"{str(metrics.get('duration') or '00:00:00'):<8} {str(metrics.get('tokens') or '↑?/↓? tok'):<15} "
        f"next: {_next_action_text(lifecycle.get('nextAction'))}",
        *_strings(progress.get("lines")),
    ]
    summary = _summary_line(progress.get("terminalSummary"))
    return _render_lines(lines=lines, terminal_summary=summary, include_summary=include_summary)


def _render_lines(*, lines: list[str], terminal_summary: str | None, include_summary: bool) -> str:
    rendered = [line for line in lines if line]
    if include_summary and terminal_summary:
        rendered.append(terminal_summary)
    if not rendered:
        raise LifecycleError("progress-terminal-lines-missing", "progress receipt has no renderable lines")
    return "\n".join(rendered)


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _summary_line(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("line"), str):
        return value["line"]
    return None


def _next_action_text(value: Any) -> str:
    if isinstance(value, dict):
        action = value.get("type")
        if isinstance(action, str) and action:
            task_ids = value.get("taskIds")
            if isinstance(task_ids, list) and task_ids:
                return f"{action} {','.join(str(item) for item in task_ids if isinstance(item, str))}"
            return action
    return "unknown"
