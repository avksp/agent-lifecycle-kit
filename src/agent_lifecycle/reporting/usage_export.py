"""Rendering helpers for usage export reports."""

from __future__ import annotations

import json
from typing import Any


def render_usage_export_json(export: dict[str, Any]) -> str:
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_usage_export_table(export: dict[str, Any]) -> str:
    rows = [
        [
            "entry",
            "adapter",
            "task",
            "operation",
            "input",
            "output",
            "total",
            "steps",
            "duration_ms",
            "budget",
            "host_cost",
        ]
    ]
    raw_entries = export.get("entries")
    entries = raw_entries if isinstance(raw_entries, list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_tokens = entry.get("tokens")
        tokens: dict[str, Any] = raw_tokens if isinstance(raw_tokens, dict) else {}
        raw_budget = entry.get("budgetDecision")
        budget: dict[str, Any] = raw_budget if isinstance(raw_budget, dict) else {}
        raw_monetary = entry.get("monetary")
        monetary: dict[str, Any] = raw_monetary if isinstance(raw_monetary, dict) else {}
        rows.append(
            [
                str(entry.get("entryId") or ""),
                str(entry.get("adapterId") or ""),
                str(entry.get("taskId") or ""),
                str(entry.get("operationId") or ""),
                str(tokens.get("input", 0)),
                str(tokens.get("output", 0)),
                str(tokens.get("total", 0)),
                str(entry.get("steps", 0)),
                str(entry.get("durationMs", 0)),
                str(budget.get("action") or budget.get("decision") or ""),
                _host_cost(monetary),
            ]
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = [" | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip() for row in rows]
    return "\n".join(rendered) + "\n"


def _host_cost(monetary: dict[str, Any]) -> str:
    if not monetary:
        return ""
    value = monetary.get("cost_usd")
    return "host-reported:null" if value is None else f"host-reported:{value}"
