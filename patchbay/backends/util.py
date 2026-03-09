from __future__ import annotations

from datetime import UTC, datetime


def format_uptime(started_at: str) -> str | None:
    """Parse an ISO 8601 timestamp and return a human-readable uptime string."""
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        delta = datetime.now(UTC) - start
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return None
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except (ValueError, TypeError):
        return None
