"""Workflow state selectors and task helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError


def ready_tasks(state: dict[str, Any]) -> list[str]:
    accepted = {
        task.get("id")
        for task in state["tasks"]
        if task.get("status") == "ACCEPTED"
    }
    ready: list[str] = []
    for task in state["tasks"]:
        if task.get("status") != "READY":
            continue
        depends_on = task.get("dependsOn", [])
        if isinstance(depends_on, list) and set(depends_on).issubset(accepted):
            ready.append(task.get("id"))
    return [task_id for task_id in ready if isinstance(task_id, str)]


def active_tasks(state: dict[str, Any]) -> list[str]:
    active_statuses = {"RUNNING", "VALIDATING", "VERIFYING", "ACCEPTANCE_PENDING"}
    return [
        task_id
        for task_id in (
            task.get("id")
            for task in state["tasks"]
            if task.get("status") in active_statuses
        )
        if isinstance(task_id, str)
    ]


def find_task(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in state["tasks"]:
        if task.get("id") == task_id:
            return task
    raise LifecycleError("unknown-task", f"unknown task: {task_id}")


def unlock_ready_tasks(state: dict[str, Any]) -> None:
    accepted = {
        task.get("id")
        for task in state["tasks"]
        if task.get("status") == "ACCEPTED"
    }
    for task in state["tasks"]:
        if task.get("status") != "PENDING":
            continue
        depends_on = task.get("dependsOn", [])
        if isinstance(depends_on, list) and set(depends_on).issubset(accepted):
            task["status"] = "READY"
