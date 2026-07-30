"""Read-only reporting views over existing lifecycle artifacts."""

from agent_lifecycle.reporting.status_view import build_status_view, require_status_view_pass

__all__ = ["build_status_view", "require_status_view_pass"]
