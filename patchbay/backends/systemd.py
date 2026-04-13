from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime

from patchbay.backends.base import (
    ServiceActionError,
    ServiceBackend,
    ServiceNotFoundError,
)

logger = logging.getLogger(__name__)

TIMEOUT = 30


def _run_systemctl(*args: str, sudo: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = ["sudo", "systemctl", *args] if sudo else ["systemctl", *args]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        raise ServiceActionError("systemctl not found; systemd is not available on this system")


def _format_uptime(timestamp_str: str) -> str | None:
    """Parse a systemctl ActiveEnterTimestamp and return a human-readable uptime.

    systemctl returns timestamps in the system's local timezone, so we parse as
    naive local time and compare against datetime.now() (also naive local time).
    """
    if not timestamp_str.strip():
        return None
    try:
        # Strip the timezone abbreviation -- we treat both sides as local time
        parts = timestamp_str.strip().rsplit(" ", 1)
        ts = parts[0] if len(parts) == 2 else timestamp_str.strip()
        start = datetime.strptime(ts, "%a %Y-%m-%d %H:%M:%S")
        delta = datetime.now() - start
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


class SystemdBackend(ServiceBackend):
    async def get_state(self, target: str) -> str:
        try:
            result = await asyncio.to_thread(_run_systemctl, "is-active", target)
        except subprocess.TimeoutExpired:
            raise ServiceActionError(f"Timed out checking state of {target}")
        output = result.stdout.strip()
        if result.returncode == 4:
            raise ServiceNotFoundError(f"Unit not found: {target}")
        state_map = {
            "active": "running",
            "inactive": "stopped",
            "failed": "error",
            "activating": "restarting",
            "deactivating": "restarting",
        }
        return state_map.get(output, "unknown")

    async def _run_action(self, action: str, target: str) -> None:
        try:
            result = await asyncio.to_thread(_run_systemctl, action, target, sudo=True)
        except subprocess.TimeoutExpired:
            raise ServiceActionError(f"Timed out running {action} on {target}")
        if result.returncode == 4:
            raise ServiceNotFoundError(f"Unit not found: {target}")
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ServiceActionError(f"Failed to {action} {target}: {stderr}")

    async def start(self, target: str) -> None:
        await self._run_action("start", target)

    async def stop(self, target: str) -> None:
        await self._run_action("stop", target)

    async def restart(self, target: str) -> None:
        await self._run_action("restart", target)

    async def get_health_info(self, target: str) -> str | None:
        return None

    async def get_uptime(self, target: str) -> str | None:
        try:
            result = await asyncio.to_thread(
                _run_systemctl, "show", "-p", "ActiveEnterTimestamp", target
            )
        except subprocess.TimeoutExpired:
            return None
        line = result.stdout.strip()
        prefix = "ActiveEnterTimestamp="
        if line.startswith(prefix):
            return _format_uptime(line[len(prefix) :])
        return None
